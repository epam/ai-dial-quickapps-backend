from quickapp.core.agent.agent_module import AgentModule


class TestAgentModuleCompletionRunners:
    def test_default_completion_hook_runners_list_is_empty(self):
        assert AgentModule().provide_completion_hook_runners() == []
