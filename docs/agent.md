# QuickApps Agent Design

## Introduction

Quick Apps is a declarative AI orchestrator that composes applications by wiring together tools, contexts, and a Large
Language Model (LLM). It enables building AI-powered applications without writing custom orchestration logic.

The core capabilities include:

- **Tool Composition**: Combine REST APIs, DIAL deployments, MCP servers, and internal tools
- **Context Management**: Attach files and user-defined contexts to conversations
- **LLM Orchestration**: Manage multi-turn interactions with automatic tool execution
- **Visual Feedback**: Display tool execution progress in the UI via stages

This document describes the internal architecture of the Quick Apps agent system.

---

## High-Level Architecture

The Quick Apps backend consists of several interconnected components that work together to process chat requests and
orchestrate tool execution.

**Main Components:**

- **Application Layer**: Handles HTTP requests, manages request context, and coordinates initialization
- **Orchestrator**: Implements the agent loop that alternates between LLM calls and tool execution
- **Tool System**: Provides a unified abstraction for different tool types with parallel execution
- **Message Pipeline**: Preprocesses messages before LLM calls and processes streaming responses
- **DI Container**: Manages component lifecycle and dependencies across request and singleton scopes

<!-- DIAGRAM: High-level architecture showing Application Layer, Orchestrator, Tool System, Message Pipeline, and DI Container with their connections -->
![High-Level Architecture](content/svg/agent_high_level.drawio.svg)

---

## Request Lifecycle

When a chat completion request arrives, it flows through several stages before the orchestrator begins its work.

### 1. Request Reception

The chat completion endpoint receives the incoming request with messages, configuration, and authentication credentials.

### 2. Context Setup

A request-scoped context is created to hold:

- API key and bearer token for authentication
- Application configuration (resolved from templates if using predefined configs)
- Conversation messages
- Response choice object for streaming output

### 3. Configuration Resolution

If the request uses predefined templates (for system prompts, tools, or toolsets), these are resolved to their actual
definitions from the predefined configuration files.

### 4. Tool Initialization

Completion initializers from each tool module are invoked to construct tool instances based on the application
configuration. Each tool type (REST API, DIAL deployment, MCP, internal) has its own initializer.

### 5. Error Handling

Any tool initialization errors are collected and displayed to the user via a dedicated error stage, allowing partial
functionality even when some tools fail to initialize.

### 6. Orchestrator Invocation

The orchestrator is retrieved from the DI container and its invoke method is called, starting the agent loop.

<!-- DIAGRAM: Request lifecycle sequence showing HTTP Request -> Context Setup -> Config Resolution -> Tool Initialization -> Error Handling -> Orchestrator Invoke -->
![Request Lifecycle](content/svg/request_lifecycle.drawio.svg)

---

## Agent Loop (Orchestrator)

The orchestrator implements a recursive agent loop that continues until the LLM produces a final response without tool
calls or the maximum iteration limit is reached.

### Loop Flow

1. **Iteration Tracking**: The iteration counter is incremented and checked against the configured maximum. If exceeded,
   the loop terminates with an error message.

2. **Attachment Notification**: Before the LLM call, the system checks whether admin-configured context files have
   changed since the last notification. If changes are detected, synthetic tool call and tool result messages are
   injected into the conversation history to inform the agent. See [Attachment Notification](#attachment-notification)
   for details.

3. **LLM Invocation**: The Assistant Invoker prepares the messages (applying pre-transformers) and calls the LLM. The
   response is streamed back.

4. **Response Processing**: The Chunk Processor accumulates streaming chunks, extracting content, attachments, and tool
   calls from the response deltas.

5. **Message Recording**: The assistant's response is appended to the conversation history.

6. **Tool Call Detection**: If the response contains tool calls, they are extracted for execution.

7. **Tool Execution**: The Tool Executor runs all requested tools in parallel, collecting their results.

8. **Result Recording**: Tool results are converted to tool messages and appended to the conversation history. The
   results are also stored in the state holder for debugging and UI display.

9. **Loop Continuation**: If tool calls were executed, the loop recurses back to step 1. Otherwise, the loop terminates
   and the final state is set.

### Termination Conditions

- **Normal Completion**: The LLM responds without any tool calls, indicating it has finished its task
- **Max Iterations Exceeded**: The configured iteration limit is reached, preventing infinite loops
- **Error**: An unrecoverable error occurs during execution

<!-- DIAGRAM: Agent loop flowchart showing the recursive flow: Increment Counter -> Check Max -> Call LLM -> Process Response -> Tool Calls? -> Yes: Execute Tools -> Record Results -> Loop Back / No: Finalize -->
![Agent Loop](content/svg/agent_loop.drawio.svg)

---

## Tool System

The tool system provides a unified abstraction for executing different types of tools while maintaining consistent
behavior for UI display, error handling, and result formatting.

### Tool Abstraction

All tools inherit from a common base class that defines:

- A standardized execution interface
- Lifecycle management with stage wrappers
- Parameter preprocessing hooks
- Attachment filtering based on configuration
- Performance timing

### Tool Types

Quick Apps supports several tool types:

- **REST API Tools**: HTTP endpoints defined declaratively in configuration
- **DIAL Deployment Tools**: Invocations of other DIAL deployments (models, applications)
- **MCP Tools**: Tools from Model Context Protocol servers
- **Internal Tools**: Built-in tools like Python interpreter, content downloader, and context notification tool

### Parallel Execution

When the LLM requests multiple tools, the Tool Executor runs them concurrently using async gathering. Each tool call is:

1. Looked up in the tool registry by name
2. Invoked with parsed arguments
3. Timed for performance tracking

Results are collected and returned in order matching the original tool calls.

### Stage Wrapper Pattern

Each tool execution is wrapped in a stage that provides visual feedback in the UI:

- **Stage Name**: Displayed title showing which tool is running
- **Parameters**: Formatted input parameters
- **Timing**: Execution duration appended to the stage name
- **Result**: Formatted output from the tool
- **Errors**: Exception information if the tool fails

The stage wrapper acts as a context manager, ensuring proper lifecycle management even when errors occur.

### Result Format

Tool results are standardized into a common format containing:

- Content (the actual result data)
- Content type (MIME type)
- Attachments (files, images, etc.)
- Usage statistics (if the tool calls an LLM internally)
- Propagation flags (which attachments should be shown in the UI)

### Error Handling

Tools support configurable fallback strategies for error handling:

- **Continue Strategy**: Returns a message instructing the LLM to try an alternative approach
- **Stop Strategy**: Terminates execution with a user-friendly error message

Errors can optionally be displayed in the stage for debugging purposes.

<!-- DIAGRAM: Tool execution flow showing ToolExecutor receiving tool calls, parallel execution via async gather, each tool wrapped in StagedBaseTool with StageWrapper, returning CompletionResults -->
![Tool Execution](content/svg/tool_execution.drawio.svg)

---

## Message Processing

Messages undergo processing both before being sent to the LLM and when receiving streaming responses.

### Pre-Transformer Pipeline

Before each LLM call, messages pass through a series of transformers that modify the message list:

1. **System Prompt Transformer**: Ensures a system message exists at the start of the conversation, combining the
   configured system prompt with any agent instructions.

2. **Attachment Reducer**: Filters user attachments to only those supported by the LLM (typically images) so that
   vision models can process them inline. Non-image attachments are removed from `custom_content`. For all user
   attachments, text metadata (`Attachment X, of type Y, url Z`) is appended to user message content so the agent
   knows which files are available.

3. **Context Attachment Transformer**: Appends configured context files as attachments to the last user message's
   `custom_content`, making them available to tools. Runs after the reducer so context files are never treated as
   user-uploaded attachments.

4. **Attachment Notification Injector**: Checks whether admin-configured context files have changed since the last
   notification. If changes are detected, inserts synthetic tool call and tool result message pairs into the history
   using the `available_context` tool. See [Attachment Notification](#attachment-notification) for details.

The transformers operate on a deep copy of the messages to avoid mutating the conversation history.

### Streaming Response Processing

LLM responses are streamed and processed incrementally by the Chunk Processor:

- **Content**: Text content is streamed directly to the response choice
- **Attachments**: Custom attachments from the LLM are extracted and added
- **Tool Calls**: Tool call deltas are accumulated and assembled into complete calls
- **Usage**: Token usage statistics are captured from the final chunk

The processor builds an aggregated result containing all accumulated data for the orchestrator to use.

<!-- DIAGRAM: Message processing pipeline showing Messages -> AddSystemPrompt -> ReduceAttachment -> AddContextAttachment -> AttachmentNotification -> LLM -> ChunkProcessor -> AssistantCallResult -->
![Message Processing](content/svg/message_processing.drawio.svg)

---

## Attachment Notification

The system uses two separate mechanisms to inform the agent about available files:

- **User attachments**: The Attachment Reducer appends text metadata to user message content (e.g.,
  `Attachment X, of type Y, url Z`). This is simple, direct, and preserves the natural conversation flow.
- **Admin context files**: The Attachment Notification Injector uses synthetic tool call/result messages via the
  `available_context` internal tool. This provides structured metadata without modifying user messages.

### Context Notification Tool

The **`available_context`** internal tool returns metadata about admin-configured context files attached to the
application. Each entry contains:

- **Title**: File name
- **URL**: DIAL-relative file URL
- **MIME Type**: Content type of the file
- **Description**: Optional admin-provided description
- **Change Status**: Whether the file is newly added since the last notification

Only metadata is returned — actual file content is not included. The agent can use the content downloader tool to fetch
file contents when needed.

### Algorithmic Injection

Before each LLM call, the `AttachmentNotificationInjector` pre-transformer checks whether admin-configured contexts
have changed since the last notification was injected.

If changes are detected, synthetic message pairs are inserted into the (deep-copied) message history:

1. An **assistant message** containing a tool call to `available_context`
2. A **tool result message** with the current metadata and change indicators

These synthetic messages appear to the LLM as if the tool was already called, giving it up-to-date context awareness
without requiring it to make the call itself.

If no changes occurred since the last injection, no messages are inserted.

### On-Demand Access

The `available_context` tool is also registered in the tool registry and available in the tool list provided to the LLM.
The agent can call it at any point during the conversation to re-check available context files.

### Interaction with Existing Components

- **Attachment Reducer**: Appends text metadata to user messages for all attachments and keeps only `image/*` inline in
  `custom_content` for vision model support.
- **Context Attachment Transformer**: Adds admin-configured context files to the last user message's `custom_content`,
  so they remain accessible to the LLM natively. The `available_context` tool provides an explicit, structured summary.
- **Python Interpreter Tool**: Continues to access attachments from user messages via `custom_content` for file
  transfer to the interpreter session.
- **Content Downloader Tool**: The agent can use this tool to fetch actual file content when needed.

---

## Dependency Injection

Quick Apps uses dependency injection extensively to manage component lifecycle and enable testability.

### Module Architecture

The application is composed of 9 specialized DI modules:

1. **App Module**: Core application, request context, FastAPI setup
2. **Agent Module**: Orchestrator, assistant invoker, pre-transformers
3. **REST API Tooling Module**: REST API tool construction
4. **DIAL Deployment Tooling Module**: Deployment tool construction
5. **MCP Tooling Module**: MCP server tool construction
6. **Internal Tool Module**: Python interpreter, content downloader
7. **Starters Module**: UI starter button configuration
8. **Configuration Support API Module**: Configuration validation endpoints
9. **DIAL Core Services Module**: DIAL Core integration

### Scoping

Components use different lifecycle scopes:

- **Singleton**: Shared across all requests (configuration, factory components)
- **Request Scope**: Created fresh for each request (context, state holder, performance timer)
- **No Scope**: Created fresh on each injection (assistant invoker, chunk processor per iteration)

### Provider Pattern

Modules expose providers that extract request-specific data from the request context and make it available to dependent
components via type-based injection. This allows components to declare their dependencies without knowing how to obtain
them.

### Initializers

Each tool module provides initializers that run during request processing to construct tools based on the application
configuration. Initializers are typed (startup, configuration, completion) and invoked at appropriate lifecycle points.

---

## Configuration

Application behavior is controlled through JSON-schema validated configuration manifests.

### Application Configuration

The root configuration contains:

- **Orchestrator**: LLM deployment, system prompt, and maximum iterations
- **Contexts**: File or user-defined contexts attached to conversations
- **Tool Sets**: Collections of tools grouped by type and shared configuration
- **Starters**: Optional UI starter buttons for common actions

### Orchestrator Settings

- **Deployment**: Which LLM model/deployment to use, with optional parameters
- **System Prompt**: Predefined or custom instructions for the agent
- **Max Iterations**: Limit on agent loop iterations to prevent runaway execution

### Tool Sets

Tools are organized into toolsets that share common configuration:

- **REST API Toolset**: Base URL, authentication, shared headers
- **Deployment Toolset**: DIAL deployment references
- **MCP Toolset**: MCP server connection configuration
- **Internal Toolset**: Built-in tool configuration
- **Predefined Toolset**: Reference to predefined tool templates

### Template Resolution

Configurations can reference predefined templates that are resolved at runtime:

- System prompts are loaded from markdown files
- Tools are loaded from JSON definitions
- Toolsets are loaded and their tools recursively resolved

This enables reusable configuration building blocks that can be shared across applications.

---

## Source Reference

For implementation details, refer to:

| Area                  | Directory                   |
|-----------------------|-----------------------------|
| Agent and processors  | `src/quickapp/agent/`       |
| Base abstractions     | `src/quickapp/common/`      |
| Request handling      | `src/quickapp/application/` |
| Configuration schemas | `src/quickapp/config/`      |
| Tool implementations  | `src/quickapp/*_tooling/`   |
