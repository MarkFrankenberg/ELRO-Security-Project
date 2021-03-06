import requests
import json

from Detectors import Detector
from Knowledge_Base import Sensitivity, Classification, log, LogLevel


class Bots(Detector):

    def __init__(self):
        super().__init__()
        self._bots_url = "{}/user_agent_parse".format(self.kb["BOTS_URL"])
        self._bots_header = {"X-API-KEY": self.kb["BOT_KEY"]}
        self._bots_data = {"parse_options": {}}

    def detect(self, parsed_data, sensitivity=Sensitivity.VerySensitive, forbidden=None, legitimate=None):
        """
        Just to be clear: there is not absolute way to determine if request arrive from legit user or not.
        We can just look for the "sloppy" guys, by checking the User-Agent.
        This method will determine if the request arrive from bot or not.
        :param parsed_data: Parsed Data (from the parser module) of the request / response
        :param sensitivity: The sensitivity of the detection
        :param forbidden: list of paths to protect
        :param legitimate: The path's that legitimate in any case for cross-site (list)
        :return: boolean
        """
        # Pre Processing
        check_pre_processing = self._pre_processing(forbidden, legitimate, parsed_data)
        if check_pre_processing == Classification.Clean:
            return False
        # ------ This code will run if the path is in the forbidden list ------ #
        user_agent = parsed_data.headers.get('User-Agent', None)
        if user_agent is None:
            return True
        self._bots_data["user_agent"] = user_agent
        user_agent_data = self.__parse_bots_data()
        if user_agent_data == Classification.NoConclusion:
            return False
        is_detected = False
        # Start Check by the web sensitivity #
        # ----- Regular ----- #
        is_detected = is_detected or user_agent_data["is_restricted"] or user_agent_data["is_abusive"]
        if sensitivity == Sensitivity.Regular or is_detected:
            return is_detected
        # ----- Sensitive  ----- #
        is_detected = is_detected or user_agent_data["is_spam"] or user_agent_data["is_weird"]
        if sensitivity == Sensitivity.Sensitive or is_detected:
            return is_detected
        # ----- Very Sensitive ----- #
        is_detected = is_detected or user_agent_data["software_type"] in self._forbidden
        if is_detected:  # Will save the computing time if its already true
            return True
        is_detected = is_detected or user_agent_data["hardware_type"] in self._forbidden
        is_detected = is_detected or len([key for key in self.kb["browsers"] if key in user_agent_data["software"]]) == 0
        return is_detected

    def __parse_bots_data(self):
        """
        This method will send request through API to get more information about the specific User-Agent
        than parse the information and return it.
        :return: dict
        """
        try:
            bots_response = requests.post(self._bots_url, data=json.dumps(self._bots_data), headers=self._bots_header)
        except Exception as e:
            log(e, LogLevel.ERROR, self.__parse_bots_data)
            # We could not get the data
            return Classification.NoConclusion
        # ---- Check that the request is succeed ---- #
        if bots_response.status_code != 200:
            return Classification.NoConclusion
        elif type(bots_response.json()) is str:
            bots_response = json.loads(bots_response.json())
        else:
            bots_response = bots_response.json()
        log("Bots response: {}".format(bots_response), LogLevel.DEBUG, self.__parse_bots_data)
        if "parse" not in bots_response:
            return Classification.NoConclusion
        # ---- Parse the information ---- #
        bots_response = bots_response["parse"]
        return {key: bots_response.get(key, value) for key, value in self.kb["bots_detectors"].items()}

    def _is_legitimate(self, legitimate, parsed_data):
        """
        This method is work on path access only.
        :param legitimate: list of legitimate path, that bots are allowed to visit.
        :param parsed_data: Parsed Data (from the parser module) of the request / response
        :return: Classification Enum
        """
        # Cleaning the request path
        req_path = parsed_data.path.strip("/")
        for path in legitimate:
            if req_path in path:
                return Classification.Clean
        return Classification.NoConclusion

    def get_forbidden_list(self):
        return self._forbidden

    def refresh(self):
        return None




