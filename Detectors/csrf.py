import logging

from Detectors import Detector, Sensitivity, Classification
from config import log_dict

logger = logging.getLogger(__name__)
logger.setLevel(logging.INFO)

formatter = logging.Formatter('%(asctime)s - %(name)s - %(levelname)s - %(message)s')

file_handler = logging.FileHandler(log_dict + "/csrf_detector.log", 'a+')
file_handler.setFormatter(formatter)

logger.addHandler(file_handler)


class CSRF(Detector):

    def __init__(self):
        super().__init__()
        self.name = "csrf_detector"

    def detect(self, parsed_data, sensitivity=Sensitivity.Regular, forbidden=None, legitimate=None):
        """
        :param parsed_data: Parsed Data (from the parser module) of the request / response
        :param sensitivity: The sensitivity of the detection
        :param forbidden: The path's that forbidden in any case for cross-site (list)
        :param legitimate: The path's that legitimate in any case for cross-site (list)
        :return: boolean
        """
        logger.info("csrf_detector got parsed_data ::--> " + parsed_data)
        # Pre Processing
        check_pre_processing = self._pre_processing(forbidden, legitimate, parsed_data)
        if check_pre_processing == Classification.Detected:
            return True
        elif check_pre_processing == Classification.Clean:
            return False
        # Getting the request Type (e.g same-origin)
        sec_fetch_site = parsed_data.headers.get('Sec-Fetch-Site', None)
        # If the request is in the same-origin return False
        if sec_fetch_site == "same-origin":  # TODO: check if the attacker can change this header
            return False
        # Sensitivity policy
        method = parsed_data.method
        if sensitivity == Sensitivity.Regular:
            if method == "POST" or method == "DELETE" or method == "PUT":
                return True
        elif sensitivity == Sensitivity.Sensitive:
            if method != "GET":
                return True
        else:  # Sensitivity.VerySensitive
            return True
        return False

    def _is_legitimate(self, legitimate, parsed_data):
        """
        The method works on path access control, there is legit path that allowed to
        access with CSRF request.
        :param legitimate: list of path
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
