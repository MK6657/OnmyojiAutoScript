# Control Center Contracts

## Authority

control-center/docs/architecture.md describes component ownership. This file describes the stable Bridge contract. OAS Core endpoints remain an upstream implementation detail and must not be called directly by the frontend.

## REST

Formal Bridge routes are under http://127.0.0.1:22367/api/v1. Health is GET /health; account, task, schedule, log, window and template routes are documented by the route definitions and must keep the /api/v1 prefix.

Success responses may contain the direct legacy payload for backward compatibility. New routes should use:

~~~json
{
  "code": "ok",
  "data": {},
  "request_id": "req_..."
}
~~~

Errors must include a stable detail.code, human-readable message and request ID. Core-unavailable is a Bridge 503; Core business rejection is a Bridge 502; invalid frontend input is 400.

Task configuration responses include a SHA-256 `revision`. A configuration PATCH is one atomic batch: callers must return that revision with the edited fields. A missing revision is HTTP 428, a stale revision is HTTP 409, and no field from either request is saved. The Bridge never fills a missing revision on behalf of a client.

## Events

The formal event stream is the Bridge WebSocket. A reconnecting frontend must reload REST state after bridge.ready; event sequence numbers are not durable across Bridge restarts.

Events must carry an event name, timestamp, account ID when applicable, sequence number and payload. The Bridge must not expose secrets, cookies or full request headers.

Core runtime commands use a JSON envelope with `command_id` and `command`. Core emits an `accepted` acknowledgement followed by exactly one `completed` or `failed` result. Bridge action success means the final result was received; successful WebSocket transmission alone is not execution success. REST fallback returns the same completion semantics.

## Runtime boundary

- Frontend calls Bridge only.
- Bridge owns UI metadata and adapts Core contracts.
- Core owns task configuration and execution.
- Mock Core/Bridge use separate ports and data directories.
- Frontend URL is dynamic; do not assume port 4175 after startup.
