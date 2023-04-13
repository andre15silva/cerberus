import abc
import os
import re
import shutil
import time
from datetime import datetime
from os.path import join
from typing import cast

from app.core import abstractions
from app.core import container
from app.core import definitions
from app.core import emitter
from app.core import utilities
from app.core import values
from app.core.task.stats import ToolStats
from app.core.utilities import error_exit
from app.core.utilities import execute_command


class AbstractTool:
    log_instrument_path = ""
    log_output_path = ""
    image_name = ""
    invoke_command = ""
    name = ""
    dir_logs = ""
    dir_output = ""
    dir_expr = ""
    dir_base_expr = ""
    cpu_usage = 1
    dir_inst = ""
    dir_setup = ""
    container_id = None
    is_instrument_only = False
    timestamp_fmt = "%a %d %b %Y %H:%M:%S %p"
    _stats = ToolStats()

    def __init__(self, tool_name):
        """add initialization commands to all tools here"""
        emitter.debug("using tool: " + tool_name)
        self.image_name = "cerberus:{}".format(tool_name.lower())

    @abc.abstractmethod
    def analyse_output(self, dir_info, bug_id, fail_list):
        """
        analyse tool output and collect information
        output of the tool is logged at self.log_output_path
        information required to be extracted are:

            self._space.non_compilable
            self._space.plausible
            self._space.size
            self._space.enumerations
            self._space.generated

            self._time.total_validation
            self._time.total_build
            self._time.timestamp_compilation
            self._time.timestamp_validation
            self._time.timestamp_plausible
        """
        return self._stats

    def clean_up(self):
        if self.container_id:
            container.remove_container(self.container_id)
        else:
            if os.path.isdir(self.dir_expr):
                rm_command = "rm -rf " + self.dir_expr
                execute_command(rm_command)

    def update_info(self, container_id, instrument_only, dir_info):
        self.container_id = container_id
        self.is_instrument_only = instrument_only
        self.update_dir_info(dir_info)
        self._stats = ToolStats()

    def update_dir_info(self, dir_info):
        if self.container_id:
            self.dir_expr = dir_info["container"]["experiment"]
            self.dir_logs = dir_info["container"]["logs"]
            self.dir_inst = dir_info["container"]["instrumentation"]
            self.dir_setup = dir_info["container"]["setup"]
            self.dir_output = dir_info["container"]["artifacts"]
            self.dir_base_expr = "/experiment"
        else:
            self.dir_expr = dir_info["local"]["experiment"]
            self.dir_logs = dir_info["local"]["logs"]
            self.dir_inst = dir_info["local"]["instrumentation"]
            self.dir_setup = dir_info["local"]["setup"]
            self.dir_output = dir_info["local"]["artifacts"]
            self.dir_base_expr = values.dir_experiments

    def timestamp_log(self):
        time_now = time.strftime("%a %d %b %Y %H:%M:%S %p")
        timestamp_txt = f"{time_now}"
        self.append_file(timestamp_txt, self.log_output_path)

    def timestamp_log_start(self):
        time_now = time.strftime("%a %d %b %Y %H:%M:%S %p")
        timestamp_txt = f"{time_now}\n"
        self.append_file(timestamp_txt, self.log_output_path)

    def timestamp_log_end(self):
        time_now = time.strftime("%a %d %b %Y %H:%M:%S %p")
        timestamp_txt = f"\n{time_now}"
        self.append_file(timestamp_txt, self.log_output_path)

    def run_command(
        self, command_str, log_file_path="/dev/null", dir_path=None, env=dict()
    ):
        """executes the specified command at the given dir_path and save the output to log_file"""
        if self.container_id:
            if not dir_path:
                dir_path = "/experiment"
            exit_code, output = container.exec_command(
                self.container_id, command_str, dir_path, env
            )
            if output:
                stdout, stderr = output
                if "/dev/null" not in log_file_path:
                    if stdout:
                        self.append_file(stdout.decode("iso-8859-1"), log_file_path)
                    if stderr:
                        self.append_file(stderr.decode("iso-8859-1"), log_file_path)
        else:
            if not dir_path:
                dir_path = self.dir_expr
            command_str += " >> {0} 2>&1".format(log_file_path)
            exit_code = execute_command(command_str, env=env, directory=dir_path)
        return exit_code

    def process_status(self, status: int):
        if status != 0:
            emitter.warning(
                "\t\t\t[warning] {0} exited with an error code {1}".format(
                    self.name, status
                )
            )
            if status == 137 and self.container_id:
                # Due to the container being killed, we restart it to be able to pull out the analysis info
                container.stop_container(self.container_id)
                container.start_container(self.container_id)

        else:
            emitter.success("\t\t\t[success] {0} ended successfully".format(self.name))

    def pre_process(self):
        """Any pre-processing required for the repair"""
        self.check_tool_exists()
        return

    def check_tool_exists(self):
        """Any pre-processing required for the repair"""
        if values.use_container:
            if self.image_name is None:
                utilities.error_exit(
                    "{} does not provide a Docker Image".format(self.name)
                )
            if ":" in self.image_name:
                repo_name, tag_name = self.image_name.split(":")
            else:
                repo_name = self.image_name
                tag_name = "latest"
            if not container.image_exists(repo_name, tag_name):
                emitter.warning("(warning) docker image not found in Docker registry")
                if container.pull_image(repo_name, tag_name) is None:
                    utilities.error_exit(
                        "{} does not provide a Docker image in Dockerhub".format(
                            self.name
                        )
                    )
                    # container.build_tool_image(repo_name, tag_name)
            else:
                # Image may exist but need to be sure it is the latest one
                emitter.information("\t\t(information) docker image found locally")
                # Get the local image
                image = container.get_image(repo_name, tag_name)
                # Then try pulling. If it is the same one we are quick
                # If not we have to wait but it is safer than getting stale resuls.
                # In theory this has a supply chain vulnerability but we can assume
                # That the storage is safe
                possibly_new_image = container.pull_image(repo_name, tag_name)

                if possibly_new_image and image.id != possibly_new_image.id:  # type: ignore
                    emitter.information(
                        "(information) docker image is not the same as the one in the repository. Will have to rebuild"
                    )
                    values.rebuild_all = True

        else:
            local_path = shutil.which(self.name.lower())
            if not local_path:
                error_exit("{} not Found".format(self.name))
        return

    def post_process(self):
        """Any post-processing required for the repair"""
        if self.container_id:
            container.stop_container(self.container_id)
        if values.is_purge:
            self.clean_up()
        return

    def print_stats(self):
        """Print the statistics of the tool."""
        pass

    def save_artifacts(self, dir_info):
        """Store all artifacts from the tool"""
        emitter.normal("\t\t\t saving artifacts of " + self.name)
        dir_results = dir_info["results"]
        dir_artifacts = dir_info["artifacts"]
        dir_logs = dir_info["logs"]
        if self.container_id:
            container.copy_file_from_container(
                self.container_id, self.dir_output, dir_results
            )
            container.copy_file_from_container(
                self.container_id, self.dir_logs, dir_results
            )
            container.copy_file_from_container(
                self.container_id, self.dir_output, dir_artifacts
            )
            container.copy_file_from_container(
                self.container_id, self.dir_logs, dir_logs
            )
            pass
        else:
            save_command = "cp -rf {}/* {};".format(self.dir_output, dir_results)
            if self.dir_logs != "":
                save_command += "cp -rf {}/* {};".format(self.dir_logs, dir_results)
            if dir_artifacts != "":
                save_command += "cp -rf {}/* {};".format(self.dir_output, dir_artifacts)
            if dir_logs != "":
                save_command += "cp -rf {}/* {}".format(self.dir_logs, dir_logs)

            execute_command(save_command)
        return

    def read_file(self, file_path, encoding="utf-8"):
        return abstractions.read_file(self.container_id, file_path, encoding)

    def read_json(self, file_path, encoding="utf-8"):
        return abstractions.read_json(self.container_id, file_path, encoding)

    def append_file(self, content, file_path):
        return abstractions.append_file(self.container_id, content, file_path)

    def write_file(self, content, file_path):
        return abstractions.write_file(self.container_id, content, file_path)

    def write_json(self, data, file_path):
        return abstractions.write_json(self.container_id, data, file_path)

    def list_dir(self, dir_path, regex=None):
        return abstractions.list_dir(self.container_id, dir_path, regex)

    def is_dir(self, dir_path):
        return abstractions.is_dir(self.container_id, dir_path)

    def is_file(self, file_path):
        return abstractions.is_file(self.container_id, file_path)

    # def get_time_stats(self):
    #     return self._stats.get_array()

    def get_output_log_path(self):
        # parse this file for time info
        if not self.log_output_path:
            regex = re.compile("(.*-output.log$)")
            for _, _, files in os.walk(self.dir_logs):
                for file in files:
                    if regex.match(file) and self.name in file:
                        self.log_output_path = os.path.join(self.dir_logs, file)
                        break
        return self.log_output_path
