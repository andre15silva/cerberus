import abc
from os.path import join

from app.core import definitions
from app.core import emitter
from app.core import utilities
from app.core.task import stats
from app.core.task.stats import ToolStats
from app.drivers.tools.AbstractTool import AbstractTool


class AbstractAnalyzeTool(AbstractTool):
    def __init__(self, tool_name):
        """add initialization commands to all tools here"""
        emitter.debug("using tool: " + tool_name)

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

    def run_analysis(self, bug_info, config_info):
        emitter.normal("\t\t(analysis-tool) analysing experiment subject")
        utilities.check_space()
        self.pre_process()
        emitter.normal("\t\t\t running analysis with " + self.name)
        conf_id = config_info[definitions.KEY_ID]
        bug_id = str(bug_info[definitions.KEY_BUG_ID])
        self.log_output_path = join(
            self.dir_logs,
            "{}-{}-{}-output.log".format(conf_id, self.name.lower(), bug_id),
        )
        self.run_command("mkdir {}".format(self.dir_output), "dev/null", "/")

    def print_stats(self):
        emitter.highlight(
            "\t\t\t time duration: {0} seconds".format(
                self._stats.time_stats.get_duration()
            )
        )
