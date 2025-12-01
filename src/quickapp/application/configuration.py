from aidial_sdk.deployment.configuration import ConfigurationResponse


# class to provide configuration response content
# all the multi-providers will be called result merged and returned to the client
class Configuration(dict):

    @classmethod
    def __merge(cls, source: dict, destination: dict) -> dict:
        for key, value in source.items():
            if isinstance(value, dict):
                node = destination.setdefault(key, {})
                cls.__merge(value, node)
            else:
                destination[key] = value
        return destination

    def merge(self, source: dict) -> "Configuration":
        merged = Configuration(self)
        self.__merge(source, merged)
        return merged

    @classmethod
    def from_list_of_configurations(cls, configurations: list["Configuration"]) -> "Configuration":
        merged_config = cls()
        for config in configurations:
            merged_config = merged_config.merge(config)
        return merged_config

    def to_configuration_response(self) -> ConfigurationResponse:
        # noinspection PyArgumentList
        return ConfigurationResponse(**self)
