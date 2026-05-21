# QuickApps Application Schema

DIAL QuickApps is a [schema-rich application](https://docs.dialx.ai/platform/core/apps#schema-rich-applications).
Schema-rich applications are defined by a JSON schema that conforms to the main meta schema.

This schema defines possible configuration options for a QuickApps application, that can be created by either admins or
end-users. It is used to validate application configuration and as a basis for editor UIs.

## Configure QuickApps in DIAL Core

In order to configure QuickApps in DIAL Core, there are two options:

### Define a schema with Application Schema Endpoint

> [!IMPORTANT]
> This option is **recommended** for all deployments, as it ensures smooth updates and compatibility with
> future versions of QuickApps without requiring manual schema management.

QuickApps expose special app schema endpoint, that can be used to fetch the latest application schema directly from the
running QuickApps instance.

Starting from DIAL Core v0.41.0, application type schema can and should be defined using this feature.

To define QuickApps application type, add the following entry to the `"applicationTypeSchemas"` array in DIAL Core
configuration, replacing `<quickapps_base_url>` with actual base URL where QuickApps service is running:
```json
{
  "applicationTypeSchemas": [
    {
      "dial:applicationTypeDisplayName": "Quick App 2.0",
      "dial:appendApplicationPropertiesHeader": false,
      "dial:applicationTypeAssistantAttachmentsInRequestSupported": true,
      "dial:applicationTypeCompletionEndpoint": "<quickapps_base_url>/openai/deployments/quick_apps2/chat/completions",
      "dial:applicationTypeConfigurationEndpoint": "<quickapps_base_url>/openai/deployments/quick_apps2/configuration",
      "dial:applicationTypeSchemaEndpoint": "<quickapps_base_url>/v1/configuration-support/application-schema",
      "dial:applicationTypeRoutes": {
        "configuration_support_read": {
          "dial:paths": ["/v1/configuration-support(/[^/]+)*$"],
          "dial:methods": ["GET"],
          "dial:rewritePath": true,
          "dial:permissions": ["WRITE"],
          "dial:upstreams": [
            {"dial:endpoint": "<quickapps_base_url>"}
          ]
        },
        "configuration_support_skill_validate": {
          "dial:paths": ["/v1/configuration-support/skills/validate$"],
          "dial:methods": ["POST"],
          "dial:rewritePath": true,
          "dial:permissions": ["WRITE"],
          "dial:upstreams": [
            {"dial:endpoint": "<quickapps_base_url>"}
          ],
          "dial:attachmentPaths": {
            "dial:requestBody": ["@.url"]
          }
        }
      },
      "$id": "https://mydial.epam.com/custom_application_schemas/quickapps2",
      "$schema": "https://dial.epam.com/application_type_schemas/schema#"
    }
  ]
}
```

`dial:applicationTypeRoutes` exposes the QuickApps configuration-support endpoints
(`/v1/configuration-support/*`) — used by the application editor to list predefined
skills, prompts, toolsets and tools — to DIAL clients through DIAL Core. The two
entries split the surface by HTTP method: a GET catch-all and a POST for skill
validation. Both are `WRITE`-gated, since configuration-support is only useful to
callers with edit access to the application. The POST entry additionally declares
`dial:attachmentPaths` so DIAL Core enforces access control on the DIAL prompt URL
carried in the request body before the request reaches QuickApps.


### Define a full application schema

> [!NOTE]
> This option is less preferred and **not recommended** for deployments, as it requires manual schema management.

Full application schema can be found in [this repository](./generated-app-schema.json).
In order to use it, copy it to the `"applicationTypeSchemas"` array in DIAL Core configuration, and replace
`<quickapps_base_url>` with actual base URL where QuickApps service is running:
```json
{
  "applicationTypeSchemas": [
    <COPIED SCHEMA>
  ]
}
```
