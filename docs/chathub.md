# DIAL ChatHub (Quickapps based)

Agentic application which can be configured to orchestrate DIAL models, applications and Python Code Interpreter as
tools.

The DIAL ChatHub is a pre-configured application based on Quickapps2.0 application type.

## Table of Contents

- [Reference Configurations](#reference-configurations)
- [Dependencies](#dependencies)
- [DIAL App Configuration](#dial-app-configuration)
- [Development](#development)
  - [Pre-requisites](#pre-requisites)
  - [Update/customise ChatHub configuration](#updatecustomise-chathub-configuration)

# Reference Configurations

The following configurations are provided as reference configurations. They can be used as a starting point for
creating your own configurations or configurations in client environments. All configurations listed here are
continuously tested for quality and features support.

# DIAL App Configuration

Examples of chathub configurations for different orchestrator models:

- [Anthropic models](../docker_compose_files/core/configuration/chathub/anthropic.json)
- [Gemini models](../docker_compose_files/core/configuration/chathub/gemini.json)
- [Openai models](../docker_compose_files/core/configuration/chathub/openai.json)

# Dependencies

ChatHub depends on models and applications deployed within DIAL. Those models and applications are configured
separately, and it's not the purpose of this documentation to cover deployment and configuration of those components.
However, ChatHub team tries to support all most recent changes in DIAL in regard to the configuration of those
components.

# Development

This section describes how to set up the development environment for ChatHub. It includes instructions for installing
dependencies, setting up the environment, and running the application locally.

## Pre-requisites

1. [Setup Quickapp local development environment](../README.md#local-development)
   1. The example configurations would be available after start of `docker compose` for Option A of Quickapp local development. 
   2. If you choose Option B, you should register applications on existing DIAL `core` service.
2. Feel free to update example configurations of ChatHub with your own models and applications deployed in DIAL. You can use reference configurations provided in this documentation as a starting point.
3. The ChatHub uses [predefined toolsets](../config/predefined/toolset) and [predefined tools](config/predefined/tools) which are based on the most recent versions of DIAL applications and models. If your DIAL Core has different models/deployments/toolsets, that you want to use, you may update the configuration files accordingly.
4. You are ready to test the ChatHub application locally.

## Update/customise ChatHub configuration

1. Open a ChatHub configuration file (e.g. `docker_compose_files/core/configuration/chathub/anthropic.json`) and find the application you want to modify, or add the new one.
2. Substitute the existing section 
```
    {
     "type": "predefined",
     "template_name": "chathub"
    }
```
   with content of [predefined ChatHub toolset](../config/predefined/toolset/chathub.json)
3. Identify the tool or toolset you want to update. They are defined in the `tools` and `toolsets` sections of the configuration file. For example, you need to change `image generation tool`, substitute:
```
    {
      "type": "predefined-tool",
      "template_name": "image_generation"
    }
```
   with proper configuration of your image generation tool. The suggested predefined tool configuration can be found [here](../config/predefined/tool/image_generation.json). You can use it as a reference for the configuration of your custom tool.
4. Restart your local DIAL Core (Option A), or register the updated/new ChatHub application in DIAL Core (Option B).
5. Test your ChatHub configuration
