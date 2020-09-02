#!/usr/bin/python
# -*- coding: utf-8 -*-
# coding = utf - 8

from __future__ import absolute_import, division, print_function, unicode_literals

import cgi
import datetime
import io
import json
import os
import threading
import time
import logging
import re

import flask
import requests
from requests_toolbelt import MultipartEncoder
import sentry_sdk

import octoprint.plugin
from octoprint.filemanager import FileDestinations
from octoprint.filemanager.util import StreamWrapper, DiskFileWrapper

from .ws import Socket
from .printer import Printer
from .backoff import BackoffTime
from .webcam import webrtc_loop
import asyncio

class MattacloudPlugin(octoprint.plugin.StartupPlugin,
                       octoprint.plugin.SettingsPlugin,
                       octoprint.plugin.TemplatePlugin,
                       octoprint.plugin.AssetPlugin,
                       octoprint.plugin.SimpleApiPlugin,
                       octoprint.plugin.EventHandlerPlugin):

    def __init__(self):
        self.printer = Printer()
        self.snapshot_count = 0
        self.new_print_job = False
        self.ws_auto_reconnect_count = 0
        self.ws_auto_reconnect = 30
        self.active_online = False
        self.ws_data_count = 0
        self.loop_time = 1.0
        self.ws_loop_time = 60
        self.sentry = sentry_sdk.init(
            "https://878e280471064d3786d9bcd063e46ad7@sentry.io/1850943"
        )
        loop = asyncio.new_event_loop()
        webrtc_thread = threading.Thread(target=webrtc_loop, args=(loop,), daemon=True)
        webrtc_thread.start()

    def get_settings_defaults(self):
        return dict(
            enabled=True,
            base_url="https://cloud.mattalabs.com/",
            authorization_token="e.g. w1il4li2am2ca1xt4on91",
            upload_dir="/home/pi/.octoprint/uploads/",
            config_print=False,
            ws_connected=False,
            num_cameras=1,
            camera_interval_1=3,
            camera_interval_2=10,
            snapshot_url_1='http://localhost:8080/?action=snapshot',
            snapshot_url_2='http://localhost:8081/?action=snapshot',
            vibration_interval=10,
            temperature_interval=1,
        )

    def get_assets(self):
        return dict(
            js=['js/mattacloud.js'],
            css=['css/mattacloud.css'],
            less=['less/mattacloud.less']
        )

    def get_template_configs(self):
        self._logger.info(
            "OctoPrint-Mattacloud - is loading template configurations.")
        return [
            dict(type="settings", custom_bindings=True)
        ]

    def get_update_information(self):
        return dict(mattacloud=dict(
            displayVersion=self._plugin_version,
            type='github_release',
            user='dougbrion',
            repo='OctoPrint-Mattacloud',
            current=self._plugin_version,
            pip='https://github.com/dougbrion/OctoPrint-Mattacloud/archive/{target_version}.zip',
        ))

    def get_printer_data(self):
        return self._printer.get_current_data()

    def get_current_job(self):
        return self._printer.get_current_job()

    def get_printer_temps(self):
        return self._printer.get_current_temperatures()

    def get_files(self):
        return self._file_manager.list_files(recursive=True)

    # TODO: Improve URL creation
    # Should write a urljoin function
    def get_base_url(self):
        if not self._settings.get(["base_url"]):
            self._logger.warning("No base URL in OctoPrint settings")
            return None

        url = self._settings.get(["base_url"])
        url = url.strip()
        if url.startswith("/"):
            url = url[1:]
        if url.endswith("/"):
            url = url[:-1]
        return url

    def get_api_url(self):
        base_url = self.get_base_url()
        url = base_url + "/api"
        return url

    def get_ws_url(self):
        api_url = self.get_api_url()
        url = api_url + "/ws/printer/"
        url = url.replace("http", "ws")
        return url

    def get_ping_url(self):
        api_url = self.get_api_url()
        url = api_url + "/ping/"
        return url

    def get_data_url(self):
        api_url = self.get_api_url()
        url = api_url + "/receive/data/"
        return url

    def get_img_url(self):
        api_url = self.get_api_url()
        url = api_url + "/receive/img/"
        return url

    def get_gcode_url(self):
        api_url = self.get_api_url()
        url = api_url + "/receive/gcode/"
        return url

    def get_request_url(self):
        api_url = self.get_api_url()
        url = api_url + "/receive/request/"
        return url

    def get_auth_token(self):
        if not self._settings.get(["authorization_token"]):
            return None
        return self._settings.get(["authorization_token"])

    def make_auth_header(self, token=None):
        if not token:
            token = self.get_auth_token()
        return {"Authorization": "Token {}".format(token)}

    def on_after_startup(self):
        self._logger.info("Starting OctoPrint-Mattacloud Plugin...")
        self.new_print_job = False
        self.ws = None
        main_thread = threading.Thread(target=self.loop)
        main_thread.daemon = True
        main_thread.start()
        self.ws_connect()
        ws_data_thread = threading.Thread(target=self.ws_send_data)
        ws_data_thread.daemon = True
        ws_data_thread.start()

    def event_ws_data(self, event, payload):
        data = self.ws_data()
        data["event"] = {
            "event_type": event,
            "payload": payload
        }
        return data

    def on_event(self, event, payload):
        if self.ws_connected():
            try:
                msg = self.event_ws_data(event, payload)
                self.ws.send_msg(msg)
            except Exception as e:
                self._logger.error(e)
                pass

    def is_enabled(self):
        return self._settings.get(["enabled"])

    def is_operational(self):
        return self._printer.is_ready() or self._printer.is_operational()

    def is_setup_complete(self):
        return self.get_base_url() and self.get_auth_token()

    def is_config_print(self):
        return self._settings.get(["config_print"])

    def has_job(self):
        if (self._printer.is_printing() or
            self._printer.is_paused() or
                self._printer.is_pausing()):
            return True
        return False

    def printer_heating(self):
        heating = False
        if self._printer.is_operational():
            heating = self._printer._comm._heating

        return heating

    def update_ws_send_interval(self):
        if self.active_online and self.has_job():
            self.ws_loop_time = 0.4
        elif self.active_online and not self.has_job():
            self.ws_loop_time = 0.8
        else:
            self.ws_loop_time = 30

    def ws_send_data(self):
        backoff = BackoffTime(max_time=300)  # 5 mins max backoff time
        while True:
            try:
                self.ws_connect()
                loop_count = 0
                loop_time = 0.1
                while self.ws_connected():
                    if self.ws_loop_time <= (loop_count * loop_time):
                        msg = self.ws_data()
                        self.ws.send_msg(msg)
                        loop_count = 0
                    time.sleep(loop_time)
                    backoff.zero()
                    loop_count += 1

            finally:
                backoff.longer()
                self._logger.error("Attempt: %s", str(backoff.attempt))
                try:
                    if self.ws is not None:
                        self.ws.disconnect()
                        self.ws = None
                except Exception as e:
                    self._logger.error("ws_send_data: %s", e)
                    pass

    def ws_connect(self):
        self._logger.info("Connecting websocket")
        self.ws = Socket(
            on_open=lambda ws: self.ws_on_open(ws),
            on_message=lambda ws, msg: self.ws_on_message(
                ws, msg),
            on_close=lambda ws: self.ws_on_close(ws),
            on_error=lambda ws, error: self.ws_on_error(
                ws, error),
            url=self.get_ws_url(),
            token=self.get_auth_token()
        )
        ws_thread = threading.Thread(target=self.ws.run)
        ws_thread.daemon = True
        ws_thread.start()
        time.sleep(3)
        self._logger.info(str(self.ws))

    def ws_available(self):
        if self.is_enabled() and hasattr(self, "ws"):
            if self.ws is not None:
                return True
        return False

    def ws_connected(self):
        if self.ws_available():
            if self.ws.connected():
                return True
        return False

    def ws_on_open(self, ws):
        self._logger.info("Opening websocket...")
        self._settings.set(["ws_connected"], True, force=True)
        self._settings.save(force=True)

    def ws_on_close(self, ws):
        self._logger.info("Closing websocket...")
        try:
            self.ws.disconnect()
            self.ws = None
        except Exception as e:
            self._logger.error("ws_on_close: %s", e)
            pass
        self._settings.set(["ws_connected"], False, force=True)
        self._settings.save(force=True)

    def ws_on_error(self, ws, error):
        # TODO: handle websocket errors
        self._logger.error("ws_on_error: %s, URL: %s, Token: %s",
                           error, self.get_base_url(), self.get_auth_token())

    def ws_on_message(self, ws, msg):
        json_msg = json.loads(msg)
        if "cmd" in json_msg:
            self.handle_cmds(json_msg)
            if self.ws_connected():
                try:
                    msg = self.ws_data()
                    self.ws.send_msg(msg)
                except Exception as e:
                    self._logger.error("ws_on_message: %s", e)
                    pass
        if "state" in json_msg:
            if json_msg["state"].lower() == "active":
                self.active_online = True
                if self.ws_connected():
                    try:
                        msg = self.ws_data()
                        self.ws.send_msg(msg)
                    except Exception as e:
                        self._logger.error("ws_on_message: %s", e)
                        pass
            else:
                self.active_online = False
        self.update_ws_send_interval()

    def ws_data(self, extra_data=None):
        # TODO: Customise what is sent depending on requirements
        data = {
            "temperature_data": self.get_printer_temps(),
            "printer_data": self.get_printer_data(),
            "timestamp": self.make_timestamp(),
            "files": self.get_files(),
            "job": self.get_current_job(),
        }
        if extra_data:
            data.update(extra_data)
        return data

    def handle_cmds(self, json_msg):
        if "cmd" in json_msg:
            if json_msg["cmd"].lower() == "pause":
                self._printer.pause_print()
            if json_msg["cmd"].lower() == "resume":
                self._printer.resume_print()
            if json_msg["cmd"].lower() == "cancel":
                self._printer.cancel_print()
            if json_msg["cmd"].lower() == "toggle":
                self._printer.toggle_pause_print()
            if json_msg["cmd"].lower() == "print":
                if "file" in json_msg and "loc" in json_msg:
                    file_to_print = json_msg["file"]
                    on_sd = True if json_msg["loc"].lower() == "sd" else False
                    self._printer.select_file(
                        json_msg["file"], sd=on_sd, printAfterSelect=True)
            if json_msg["cmd"].lower() == "select":
                if "file" in json_msg and "loc" in json_msg:
                    file_to_print = json_msg["file"]
                    on_sd = True if json_msg["loc"].lower() == "sd" else False
                    self._printer.select_file(json_msg["file"], sd=on_sd)
            if json_msg["cmd"].lower() == "home":
                if "axes" in json_msg:
                    axes = json_msg["axes"]
                    # TODO: Deal with one or multiple axes
                    self._printer.home(axes=axes)
                else:
                    self._printer.home()
            if json_msg["cmd"].lower() == "jog":
                if "axes" in json_msg:
                    axes = json_msg["axes"]
                    # TODO: Check if axes dict is valid
                    # Axes and distances to jog, keys are axes (“x”, “y”, “z”),
                    # values are distances in mm
                    self._printer.jog(axes=axes, relative=True)
            if json_msg["cmd"].lower() == "extrude":
                if "amt" in json_msg:
                    amt = json_msg["amt"]
                    self._printer.extrude(amount=amt)
            if json_msg["cmd"].lower() == "retract":
                if "amt" in json_msg:
                    amt = -json_msg["amt"]
                    self._printer.extrude(amount=amt)
            if json_msg["cmd"].lower() == "change_tool":
                if "tool" in json_msg:
                    new_tool = "tool{}".format(json_msg["tool"])
                    self._printer.change_tool(tool=new_tool)
            if json_msg["cmd"].lower() == "feed_rate":
                if "factor" in json_msg:
                    new_factor = json_msg["factor"]
                    # TODO: Add checking to see if valid factor
                    # Percentage expressed as either an int between 0 and 100
                    # or a float between 0 and 1.
                    self._printer.feed_rate(factor=new_factor)
            if json_msg["cmd"].lower() == "flow_rate":
                if "factor" in json_msg:
                    new_factor = json_msg["factor"]
                    # TODO: Add checking to see if valid factor
                    # Percentage expressed as either an int between 0 and 100
                    # or a float between 0 and 1.
                    flow_cmd = "M221 S{}".format(new_factor)
                    self._printer.commands(commands=flow_cmd)
                    self._printer.commands(commands="M221")
            if json_msg["cmd"].lower() == "gcode":
                if "commands" in json_msg:
                    gcode_cmds = json_msg["commands"]
                    # TODO: Check if single (str) or multiple (lst)
                    self._printer.commands(commands=gcode_cmds)
            if json_msg["cmd"].lower() == "temperature":
                if "heater" in json_msg and "val" in json_msg:
                    # TODO: More elegantly handle different inputs
                    # e.g. bed, tool0, tool1, 0, 1
                    heater = json_msg["heater"]
                    if heater != "bed":
                        heater = "tool{}".format(heater)
                    val = json_msg["val"]
                    self._printer.set_temperature(heater=heater, value=val)
            if json_msg["cmd"].lower() == "temperature_offset":
                if "offsets" in json_msg:
                    # TODO: Validate the "offsets" dict
                    # Keys must match the format for the heater parameter
                    # to set_temperature(), so “bed” for the offset for the
                    # bed target temperature and “tool[0-9]+” for the
                    # offsets to the hotend target temperatures.
                    offsets = json_msg["offsets"]
                    self._printer.set_temperature_offset(offsets)
            if json_msg["cmd"].lower() == "z_adjust":
                if "height" in json_msg:
                    height = json_msg["height"]
                    z_adjust_cmd = "M206 Z{}".format(height)
                    self._printer.commands(commands=z_adjust_cmd)
            if json_msg["cmd"].lower() == "upload_request":
                # TODO: Add loc to server side
                if "id" in json_msg and "loc" in json_msg:
                    if json_msg["loc"].lower() == "sd":
                        location = FileDestinations.SDCARD
                    elif json_msg["loc"].lower() == "local":
                        location = FileDestinations.LOCAL
                    else:
                        # TODO: Handle this error
                        location = FileDestinations.LOCAL
                        self._logger.warning("Invalid file destination: %s",
                                             json_msg["loc"].lower())
                    path = self.post_upload_request(file_id=json_msg["id"])
                    # TODO: Handle analysis for SD card files
                    is_analysed = self._file_manager.has_analysis(destination=location,
                                                                  path=path)
                    if not is_analysed:
                        pass
            if json_msg["cmd"].lower() == "new_folder":
                if "folder" in json_msg and "loc" in json_msg:
                    folder_name = json_msg["folder"]
                    if json_msg["loc"].lower() == "sd":
                        location = FileDestinations.SDCARD
                    elif json_msg["loc"].lower() == "local":
                        location = FileDestinations.LOCAL
                    else:
                        # TODO: Handle this error
                        location = FileDestinations.LOCAL
                        self._logger.warning("Invalid file destination: %s",
                                             json_msg["loc"].lower())
                    # TODO: Destination both local and SD card.
                    self._file_manager.add_folder(destination=location,
                                                  path=folder_name,
                                                  ignore_existing=True,
                                                  display=None)
            if json_msg["cmd"].lower() == "delete":
                if "file" in json_msg and "loc" in json_msg and "type" in json_msg:
                    file_to_delete = json_msg["file"]
                    if json_msg["loc"].lower() == "sd":
                        location = FileDestinations.SDCARD
                    elif json_msg["loc"].lower() == "local":
                        location = FileDestinations.LOCAL
                    else:
                        # TODO: Handle this error
                        location = FileDestinations.LOCAL
                        self._logger.warning("Invalid file destination: %s",
                                             json_msg["loc"].lower())
                    if json_msg["type"].lower() == "file":
                        self._file_manager.remove_file(destination=location,
                                                       path=file_to_delete)
                    elif json_msg["type"].lower() == "folder":
                        self._file_manager.remove_folder(destination=location,
                                                         path=file_to_delete)
                    else:
                        self._logger.warning(
                            "Incorrect type file/folder provided: %s",
                            json_msg["type"].lower())
            if json_msg["cmd"].lower() == "webrtc_start_server_printer":
                try:
                    resp = requests.post(
                        url="http://127.0.0.1:8888/offer",
                        data=json.dumps(json_msg),
                        headers={
                            'Content-Type': 'application/json'
                        },
                    )
                    resp.raise_for_status()
                    webrtc_resp = {
                        "webrtc_reply_printer_server": json.loads(resp.content)
                    }
                    self._logger.info("BEFORE WS SEND")
                    msg = self.ws_data(extra_data=webrtc_resp)
                    self.ws.send_msg(msg)
                    self._logger.info("AFTER WS SEND")
                except requests.exceptions.RequestException as e:
                    self._logger.error(e)


    def process_response(self, resp):
        # TODO: Handle different types of response
        content_disposition = resp.headers["Content-Disposition"]
        value, params = cgi.parse_header(content_disposition)
        filename = params["filename"]
        file_content = resp.text.replace("\\n", "\n")
        stream = io.StringIO(file_content, newline="\n")
        stream_wrapper = StreamWrapper(filename, stream)

        try:
            future_path, future_filename = self._file_manager.sanitize(
                FileDestinations.LOCAL, filename)
        except Exception as e:
            future_path = None
            future_filename = None
        future_full_path = self._file_manager.join_path(
            FileDestinations.LOCAL, future_path, future_filename)
        future_full_path_in_storage = self._file_manager.path_in_storage(
            FileDestinations.LOCAL, future_full_path)

        if not self._printer.can_modify_file(future_full_path_in_storage, False):
            return

        reselect = self._printer.is_current_file(
            future_full_path_in_storage, False)
        # Destination both local and SD card.
        path = self._file_manager.add_file(destination=FileDestinations.LOCAL,
                                           path=filename,
                                           file_object=stream_wrapper,
                                           allow_overwrite=True)
        if os.path.exists(path):
            try:
                os.remove(path)
            except (OSError, IOError) as e:
                pass

        if reselect:
            self._printer.select_file(self._file_manager.path_on_disk(FileDestinations.LOCAL,
                                                                      added_file),
                                      False)
        return path

    def make_timestamp(self):
        dt = datetime.datetime.utcnow().strftime("%Y-%m-%d %H:%M:%S")
        return dt

    def post_gcode(self, gcode=None):
        self._logger.debug("Posting gcode")

        if not self.is_setup_complete():
            self._logger.warning("Printer not ready")
            return

        if not gcode:
            job_info = self.get_current_job()
            gcode_name = job_info["file"]["name"]
            gcode_path = job_info["file"]["path"]
            upload_dir = self._settings.get(["upload_dir"])
            path = os.path.join(upload_dir, gcode_path)
            if os.path.exists(path):
                try:
                    with open(path, "rb") as gcode:
                        data = MultipartEncoder(
                            fields={
                                "gcode": (gcode_name, gcode, "text/plain"),
                                "timestamp": self.make_timestamp(),
                            }
                        )

                        url = self.get_gcode_url()
                        headers = self.make_auth_header()
                        extra_headers = {"Content-Type": data.content_type}
                        headers.update(extra_headers)

                        try:
                            resp = requests.post(
                                url=url,
                                data=data,
                                headers=headers,
                            )
                            resp.raise_for_status()
                        except requests.exceptions.RequestException as e:
                            self._logger.warning(
                                "Posting gcode: %s, URL: %s, Headers: %s",
                                e, url, self.make_auth_header())

                except (OSError, IOError) as e:
                    self._logger.warning(
                        "Failed to open gcode file: %s, Path: %s", e, path)
            else:
                self._logger.warning("Gcode file path does not exist: %s", path)

    def post_img(self, img=None, camera="primary"):
        self._logger.debug("Posting image")

        if not self.is_setup_complete():
            self._logger.warning("Printer not ready")
            return

        url = self.get_img_url()

        if not img:
            pass

        files = {
            "img": img,
        }

        data = {
            "timestamp": self.make_timestamp(),
            "camera": camera,
        }

        try:
            resp = requests.post(
                url=url,
                files=files,
                data=data,
                headers=self.make_auth_header()
            )
            resp.raise_for_status()

        except requests.exceptions.RequestException as e:
            self._logger.warning(
                "Posting image: %s, URL: %s, Headers %s",
                e, url, self.make_auth_header())

    def post_raw_img(self, filename, raw_img, camera="primary"):
        self._logger.debug("Posting raw image")

        if not self.is_setup_complete():
            self._logger.warning("Printer not ready")
            return

        url = self.get_img_url()

        files = {
            "img": (filename, raw_img),
        }

        data = {
            "timestamp": self.make_timestamp(),
            "camera": camera,
        }

        try:
            resp = requests.post(
                url=url,
                files=files,
                data=data,
                headers=self.make_auth_header()
            )
            resp.raise_for_status()

        except requests.exceptions.RequestException as e:
            self._logger.warning(
                "Posting raw image: %s, URL: %s, Headers %s",
                e, url, self.make_auth_header())

    def post_upload_request(self, file_id):
        self._logger.debug("Posting upload request")

        if not self.is_setup_complete():
            self._logger.warning("Printer not ready")
            return

        path = None

        data = {
            "timestamp": self.make_timestamp(),
            "status": "ready",
            "type": "file",
            "file_id": file_id,
        }

        url = self.get_request_url()

        try:
            resp = requests.post(
                url=url,
                json=data,
                headers=self.make_auth_header()
            )
            resp.raise_for_status()
            path = self.process_response(resp)

            data = {
                "timestamp": self.make_timestamp(),
                "status": "success",
                "type": "file",
                "file_id": file_id,
            }

            try:
                resp = requests.post(
                    url=url,
                    json=data,
                    headers=self.make_auth_header()
                )
                resp.raise_for_status()

            except requests.exceptions.RequestException as e:
                self._logger.warning(
                    "Posting upload request (1st post): %s, URL: %s, Headers %s",
                    e, url, self.make_auth_header())

        except requests.exceptions.RequestException as e:
            self._logger.warning(
                "Posting upload request  (2st post): %s, URL: %s, Headers %s",
                e, url, self.make_auth_header())

        return path

    def get_api_commands(self):
        return dict(
            test_auth_token=["auth_token"],
            set_enabled=[],
            set_config_print=[],
            ws_reconnect=[],
        )

    def is_api_adminonly(self):
        return True

    def on_api_command(self, command, data):
        if command == "test_auth_token":
            auth_token = data["auth_token"]
            success, status_text = self.test_auth_token(token=auth_token)
            if success:
                self._settings.set(["authorization_token"],
                                   auth_token, force=True)
                self._settings.save(force=True)
            return flask.jsonify({"success": success, "text": status_text})
        if command == "ws_reconnect":
            self.ws_connect()
            # TODO: Improve this... hacky wait for the websocket to connect
            if self.ws_connected():
                status_text = "Successfully connected to mattacloud."
                success = True
            else:
                status_text = "Failed to connect to mattacloud."
                success = False

            return flask.jsonify({"success": success, "text": status_text})

        if command == "set_enabled":
            previous_enabled = self._settings.get(["enabled"])
            self._settings.set(["enabled"], not previous_enabled, force=True)
            self._settings.save(force=True)
            is_enabled = self._settings.get(["enabled"])
            return flask.jsonify({"success": True, "enabled": is_enabled})
        if command == "set_config_print":
            previous_config_print = self._settings.get(["config_print"])
            self._settings.set(
                ["config_print"], not previous_config_print, force=True)
            self._settings.save(force=True)
            is_config_print = not previous_config_print
            return flask.jsonify({"success": True, "config_print_enabled": is_config_print})

    def test_auth_token(self, token):
        # TODO: Returns Success if the token is an empty string!!!!
        url = self.get_ping_url()
        success = False
        status_text = "Oh no! An unknown error occurred."
        if token == "":
            status_text = "Please enter a token."
            return success, status_text
        try:
            resp = requests.get(
                url=url,
                headers=self.make_auth_header(token=token)
            )
            success = resp.ok
            if resp.status_code == 200:
                status_text = "All is tickety boo! Your token is valid."
            elif resp.status_code == 401:
                status_text = "Whoopsie. That token is invalid."
            else:
                status_text = "Oh no! An unknown error occurred."
        except requests.exceptions.RequestException as e:
            self._logger.warning(
                "Testing authorization token: %s, URL: %s, Headers %s",
                e, url, self.make_auth_header())
            status_text = "Error. Please check OctoPrint\'s internet connection"
            # TODO: Catch the correct exceptions
        return success, status_text

    def is_new_job(self):
        if self.has_job():
            if self.new_print_job:
                self.post_gcode()
                self.new_print_job = False
                self._printer.commands(commands="M221")  # check flow rate
        elif self.is_operational():
            self.new_print_job = True
            self.snapshot_count = 0

    def parse_received_lines(self, comm, line, *args, **kwargs):
        if "Flow" in line:
            flow_regex = re.compile(r"Flow: (\d+)\%")
            match = flow_regex.search(line)
            if match:
                flow_rate = int(match.group(1))
                extra_data = {
                    'flow_rate': flow_rate,
                }
                if self.ws_connected():
                    try:
                        msg = self.ws_data(extra_data=extra_data)
                        self.ws.send_msg(msg)
                    except Exception as e:
                        self._logger.error(e)
                        pass
        return line

    def camera_snapshot(self, snapshot_url, cam_count=1):
        try:
            resp = requests.get(
                snapshot_url,
                stream=True
            )
            resp.raw.decode_content = True
            job_details = self.get_current_job()
            print_name, _ = os.path.splitext(job_details["file"]["name"])
            snapshot_name = '{}-{}-cam{}.jpg'.format(print_name,
                                                     self.snapshot_count,
                                                     cam_count)
            self.snapshot_count += 1
            return snapshot_name, resp.raw
        except requests.exceptions.RequestException as e:
            self._logger.warning(
                "Camera snapshot: %s, URL: %s",
                e, snapshot_url)
            return None, None

    def loop(self):
        camera_count_1 = 0
        camera_count_2 = 0
        while True:
            num_cameras = int(self._settings.get(["num_cameras"]))
            if self.is_enabled():
                if not self.is_setup_complete():
                    self._logger.warning(
                        "Invalid URL, Authorization Token or Spookiness")
                    time.sleep(1)
                    continue

                self.is_new_job()

                if self.has_job() and num_cameras > 0:
                    camera_interval_1 = int(
                        self._settings.get(["camera_interval_1"]))
                    if (camera_count_1 * self.loop_time) > camera_interval_1:
                        snapshot_url = self._settings.get(["snapshot_url_1"])
                        filename, img = self.camera_snapshot(snapshot_url)
                        if filename and img:
                            self.post_raw_img(filename, img, camera="primary")
                        camera_count_1 = 0
                    camera_count_1 += 1

                    if num_cameras > 1:
                        camera_interval_2 = int(
                            self._settings.get(["camera_interval_2"]))
                        if (camera_count_2 * self.loop_time) > camera_interval_2:
                            snapshot_url = self._settings.get(
                                ["snapshot_url_2"])
                            filename, img = self.camera_snapshot(
                                snapshot_url, cam_count=2)
                            if filename and img:
                                self.post_raw_img(filename, img, camera="secondary")
                            camera_count_2 = 0
                        camera_count_2 += 1

            time.sleep(self.loop_time)


__plugin_name__ = "Mattacloud"
__plugin_pythoncompat__ = ">=2.7,<4"

def __plugin_load__():
    global __plugin_implementation__
    __plugin_implementation__ = MattacloudPlugin()
    global __plugin_hooks__
    __plugin_hooks__ = {
        "octoprint.plugin.softwareupdate.check_config": __plugin_implementation__.get_update_information,
        "octoprint.comm.protocol.gcode.received": __plugin_implementation__.parse_received_lines,
    }
