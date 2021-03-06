from urllib.parse import urlparse
from passlib.handlers.sha2_crypt import sha256_crypt
from functools import wraps
import requests
from flask import Flask, request
from flask_restful import Resource, Api

from DBAgent.orm import Users, Services, Server, DetectorRequestData
from Detectors import UserProtectionDetector
from Knowledge_Base import log, to_json, LogLevel
from Parser.parser import HTTPResponseParser
from config import db, authorized_servers


app = Flask(__name__)
api = Api(app)


services_credentials = ["ip", "website", "sql_detector", "bots_detector", "xss_detector", "xml_detector",
                        "csrf_detector", "bruteforce_detector"]


def required_authentication(func):
    @wraps(func)
    def wrapper(self, *args, **kwargs):
        if request.remote_addr not in authorized_servers:
            log("[API][required_authentication] Block the request from {}".format(request.remote_addr), LogLevel.INFO, self.post)
            return {"msg": "Your not authorized to perform this action", "ip": request.remote_addr, "contact": "contact@elro-sec.com"}
        return func(self, *args, **kwargs)

    return wrapper


def only_json(func):
    @wraps(func)
    def wrapper(self, *args, **kwargs):
        if not request.is_json:
            log("[API][only_json] Could not process the request, is_json: {}".format(request.is_json), LogLevel.INFO, self.post)
            return {"msg": "Please send json request.", "ip": request.remote_addr, "contact": "contact@elro-sec.com"}
        if request.get_json() is None:
            log("[API][only_json] Could not process the request, get_json: None", LogLevel.INFO, self.post)
            return {"msg": "Please send json with the request.", "ip": request.remote_addr, "contact": "contact@elro-sec.com"}
        return func(self, *args, **kwargs)

    return wrapper


class LoginHandler(Resource):

    @required_authentication
    @only_json
    def post(self):
        incoming_json = request.get_json()
        errors = check_json_object(incoming_json, ["email", "password"],
                                   "Could not find {} at the incoming json object.")
        if len(errors) > 0:
            log("[API][LoginHandler] Could not process the request: {}".format(errors), LogLevel.INFO, self.post)
            return 0
        user = db.get_session().query(Users).filter(Users.email == incoming_json['email']).first()
        if user is None:
            log("[API][LoginHandler] Could not locate the {} user: ".format(incoming_json['email']), LogLevel.INFO, self.post)
            return 0
        verify = sha256_crypt.verify(str(incoming_json['password']), user.password)
        if verify:
            if user.is_admin == 1:
                log("[API][LoginHandler] Admin login has occurred: {}".format(incoming_json['email']), LogLevel.INFO, self.post)
                return 2
            return 1
        log("[API][LoginHandler] Login Failure has occurred:: {} {}".format(request.remote_addr, incoming_json['email']), LogLevel.INFO, self.post)
        return 0


def create_services_object(user_id, incoming_json, server_id):
    users_services = Services(user_id=user_id,
                              sql_detector=int(incoming_json['services']['sql_detector']),
                              bots_detector=int(incoming_json['services']['bots_detector']),
                              xss_detector=int(incoming_json['services']['xss_detector']),
                              xml_detector=int(incoming_json['services']['xml_detector']),
                              csrf_detector=int(incoming_json['services']['csrf_detector']),
                              bruteforce_detector=int(incoming_json['services']['bruteforce_detector']),
                              server_id=server_id)
    return users_services


def check_json_object(json_object, credential_list, message):
    return [message.format(field) for field in credential_list if field not in json_object]


class RegisterHandler(Resource):
    """ registers a new client, and his protection preferences """

    @required_authentication
    @only_json
    def post(self):
        incoming_json = request.get_json()
        errors = check_json_object(incoming_json, ["users", "services"], "Could not find {} at the incoming json object.")
        if len(errors) > 0:
            log("[API][RegisterHandler] Could not process the request: {}".format(errors), LogLevel.INFO, self.post)
            return 0
        errors += check_json_object(incoming_json['users'], ["email", "password"], "Missing {} for the user credentials")
        if len(errors) > 0:
            log("[API][RegisterHandler] Could not process the request: {}".format(errors), LogLevel.INFO, self.post)
            return 0
        errors += check_json_object(incoming_json['services'], services_credentials,
                                    message="Missing {} for the services credentials")
        if len(errors) > 0:
            log("[API][RegisterHandler] Could not process the request: {}".format(errors), LogLevel.INFO, self.post)
            return 0
        log("[API][RegisterHandler] Registering new Client: {}".format(incoming_json['users']['email']), LogLevel.INFO, self.post)
        user = Users(email=incoming_json['users']['email'],
                     password=sha256_crypt.hash(str(incoming_json['users']['password'])))
        try:
            db.insert(user)
        except Exception as e:
            errors = [str(e)]
        finally:
            if user.item_id is None:
                log("[API][RegisterHandler] Could not insert the user into the database, contact the server "
                    "administrator: {} ".format(errors), LogLevel.INFO, self.post)
                return 0
        server = Server(user_id=user.item_id,
                         server_ip=incoming_json['services']['ip'],
                         server_dns=incoming_json['services']['website'])
        try:
            db.insert(server)
        except Exception as e:
            errors = [str(e)]
        finally:
            if server.item_id is None:
                log("[API][RegisterHandler] Could not insert the server into the database, contact the server "
                    "administrator: {} ".format(errors), LogLevel.INFO, self.post)
                return 0
        user_services = create_services_object(user_id=user.item_id, incoming_json=incoming_json,
                                               server_id=server.item_id)
        try:
            db.insert(user_services)
        except Exception as e:
            errors = [str(e)]
        finally:
            if user_services.item_id is None:
                log("[API][RegisterHandler] Could not insert the services into the database, contact the server "
                    "administrator: {} ".format(errors), LogLevel.INFO, self.post)
                return 0
        return 1


class GetActiveServicesHandler(Resource):

    @required_authentication
    @only_json
    def post(self):
        def count_total_records(key):
            return db.get_session().query(DetectorRequestData).filter_by(detected=key).count()

        def count_server_records(server_id, key):
            return db.get_session().query(DetectorRequestData).filter_by(detected=key, to_server_id=server_id).count()

        incoming_json = request.get_json()
        errors = check_json_object(incoming_json, ["email"], "Could not find {} at the incoming json object.")
        if len(errors) > 0:
            log("[API][GetActiveServicesHandler] Could not process the request: {}".format(errors), LogLevel.INFO, self.post)
            return False
        user = db.get_session().query(Users).filter(Users.email == incoming_json["email"]).first()
        if user is None:
            log("[API][GetActiveServicesHandler] Could not find the user in the DB: {}".format(incoming_json["email"]), LogLevel.INFO, self.post)
            return False
        try:
            joined_statuses = []
            all_servers = db.get_session().query(Server).filter(Server.user_id == user.item_id).all()
            log("[API][GetActiveServicesHandler] all_servers: {}".format(all_servers), LogLevel.INFO, self.post)
            for server in all_servers:
                log("[API][GetActiveServicesHandler] server: {}".format(server), LogLevel.INFO, self.post)
                services = db.get_session().query(Services).filter(Services.server_id == server.item_id).first()
                if services is None:
                    log("[API][GetActiveServicesHandler] Could not find the services in the DB: {}".format(
                        server.server_dns), LogLevel.INFO, self.post)
                    return False
                jsoned_services = to_json(services, ignore_list=["server_id", "user_id", "id", "created_on"], to_str=True)
                final_services_json = {
                    key: {
                        "state": value,
                        "count": count_total_records(key) if user.is_admin else count_server_records(server.item_id, key)
                    }
                    for key, value in jsoned_services.items()
                }
                log("[API][GetActiveServicesHandler] final_services_json: {}".format(final_services_json), LogLevel.INFO, self.post)
                joined_object = {**final_services_json, **to_json(server, to_str=True)}
                joined_object['website'] = joined_object['server_dns']
                del joined_object['server_dns']
                joined_statuses.append(joined_object)
            log("[API][GetActiveServicesHandler] return {}".format(joined_statuses), LogLevel.DEBUG, self.post)
            return joined_statuses
        except Exception as e:
            log("[API][GetActiveServicesHandler] Exception: {}".format(e), LogLevel.ERROR, self.post)
            return False


class GetUsersDataHandler(Resource):

    @required_authentication
    def post(self):
        all_users = db.get_session().query(Users).all()
        all_servers = db.get_session().query(Server).all()
        all_services = db.get_session().query(Services).all()
        joined_objects = []
        for user in all_users:
            current_object = to_json(user, to_str=True)
            del current_object["password"]
            for server in all_servers:
                if server.user_id == user.item_id:
                    current_object = {**current_object, **to_json(server, to_str=True)}
                    for service in all_services:
                        if service.server_id == server.item_id:
                            current_object = {**current_object, **to_json(service, ignore_list=["server_id", "user_id", "id", "created_on"], to_str=True)}
                            joined_objects.append(current_object)
        log("[API][GetUsersDataHandler] joined_objects: {}".format(joined_objects), LogLevel.DEBUG, self.post)

        return joined_objects


class TestAPI(Resource):

    @required_authentication
    def post(self):
        return {'bye': 'world'}


class UpdateServiceStatusHandler(Resource):

    @required_authentication
    @only_json
    def post(self):
        incoming_json = request.get_json()
        errors = check_json_object(incoming_json, ["website", "update_data"], "Could not find {} at the incoming json object.")
        if len(errors) > 0:
            log("[API][UpdateServiceStatusHandler] Could not process the request: {}".format(errors), LogLevel.INFO, self.post)
            return 0
        server = db.get_session().query(Server).filter(Server.server_dns == incoming_json['website']).first()
        if server is None:
            log("[API][UpdateServiceStatusHandler] Could not find the server at the Database: {}"
                .format(incoming_json['website']), LogLevel.INFO, self.post)
            return 0
        update_data = incoming_json['update_data']
        update_data_final = {k: 1 if v == 'True' else 0 for k, v in update_data.items()}
        log("[API][UpdateServiceStatusHandler] Services update_data_final: {}".format(update_data_final), LogLevel.INFO, self.post)
        sess = db.get_session()
        sess.query(Services).filter(Services.server_id == server.item_id).update(update_data_final)
        sess.commit()
        log("[API][UpdateServiceStatusHandler] Services update successfully for: {}".format(server.server_dns), LogLevel.INFO,
            self.post)
        return 1


class AdminUpdateServiceStatusHandler(Resource):

    @required_authentication
    @only_json
    def post(self):
        incoming_json = request.get_json()
        errors = check_json_object(incoming_json, ["update_data"], "Could not find {} at the incoming json object.")
        if len(errors) > 0:
            log("[API][AdminUpdateServiceStatusHandler] Could not process the request: {}".format(errors), LogLevel.INFO, self.post)
            return 0
        log("[API][AdminUpdateServiceStatusHandler] admin update: {}"
            .format(type(incoming_json['update_data'])), LogLevel.DEBUG, self.post)
        update_data = incoming_json['update_data']
        sess = db.get_session()
        sess.query(Services).update(update_data)
        sess.commit()
        log("[API][AdminUpdateServiceStatusHandler] Date updated: {}".format(incoming_json['update_data']),
            LogLevel.DEBUG, self.post)
        return 1


class AddNewWebsiteHandler(Resource):
    """ adding a new website, and its specific protection preferences to an existing client """

    @required_authentication
    @only_json
    def post(self):
        incoming_json = request.get_json()
        errors = check_json_object(incoming_json, ["email", "services"], "Could not find {} at the incoming json object.")
        if len(errors) > 0:
            log("[API][AddNewWebsiteHandler] Could not process the request: {}".format(errors), LogLevel.INFO, self.post)
            return 0
        errors = check_json_object(incoming_json["services"], services_credentials,
                                   "Could not find {} at the services json object.")
        if len(errors) > 0:
            log("[API][AddNewWebsiteHandler] Could not process the request: {}".format(errors), LogLevel.INFO, self.post)
            return 0
        user = db.get_session().query(Users).filter(Users.email == incoming_json["email"]).first()
        if user is None:
            log("[API][AddNewWebsiteHandler] Could not find this user at the datABASE: {}".format(incoming_json["email"]), LogLevel.INFO, self.post)
            return 0
        server = Server(user_id=user.item_id,
                        server_ip=incoming_json['services']['ip'],
                        server_dns=incoming_json['services']['website'])
        try:
            db.insert(server)
        except Exception as e:
            errors = [e]
        finally:
            if server.item_id is None:
                log("[API][RegisterHandler] Could not insert the server into the database, contact the server "
                    "administrator: {} ".format(errors), LogLevel.INFO, self.post)
                return 0
        users_services = create_services_object(user_id=user.item_id, incoming_json=incoming_json, server_id=server.item_id)
        try:
            db.insert(users_services)  # TODO: Royi this is Duplicate code (just copy past from register user)
        except Exception as e:
            errors = [str(e)]
        finally:
            if users_services.item_id is None:
                log("[API][AddNewWebsiteHandler] Could not insert the services into the database, contact the server "
                    "administrator: {} ".format(errors), LogLevel.INFO, self.post)
                return 0
        return 1


class UserProtectorHandler(Resource):

    @required_authentication
    @only_json
    def post(self):
        incoming_json = request.get_json()
        errors = check_json_object(incoming_json, ["host_name"], "Could not find {} at the incoming json object.")
        if len(errors) > 0:
            log("[API][UserProtectorHandler] Could not process the request: {}".format(errors), LogLevel.INFO, self.post)
            return 0
        host_to_detect = urlparse(str(incoming_json['host_name']))
        host_to_detect = '{uri.netloc}'.format(uri=host_to_detect).lower()
        if len(host_to_detect) < 3:
            log("[API][UserProtectorHandler] Could not detect this host: {}".format(host_to_detect), LogLevel.INFO, self.post)
            return 0
        host_to_detect = "https://{}".format(host_to_detect)
        log("[API][UserProtectorHandler] getting info with UserProtectionDetector for: {}"
            .format(host_to_detect), LogLevel.INFO, self.post)
        try:
            response = requests.get(host_to_detect)
        except Exception as e:
            log("[API][UserProtectorHandler] Could not get response: {}".format(e), LogLevel.ERROR, self.post)
            return {"alerts": ["We could not process the request, please check that the url is valid."]}
        parser = HTTPResponseParser(None)
        parsed_response = parser.parse(response, is_user_protection=True)
        upc = UserProtectionDetector(parsed_response)
        resp = upc.detect(255)
        return {"alerts": resp.detected_alerts}


api.add_resource(LoginHandler, '/login')
api.add_resource(RegisterHandler, '/register')
api.add_resource(GetActiveServicesHandler, '/getActiveServices')
api.add_resource(GetUsersDataHandler, '/getUsersData')
api.add_resource(TestAPI, '/TestAPI')
api.add_resource(UpdateServiceStatusHandler, '/updateServiceStatus')
api.add_resource(AdminUpdateServiceStatusHandler, '/adminUpdateServiceStatus')
api.add_resource(AddNewWebsiteHandler, '/addNewWebsite')
api.add_resource(UserProtectorHandler, '/userProtector')

