// Live Go AI-agent framework smoke driver module (AAASM-3525).
//
// A standalone module so the driver compiles against the real go-sdk AND a real
// AI-agent framework (LangChainGo) without pulling either into the integration
// repo's Python-only dependency set. The module path uses the go-sdk's actual
// declared, lowercase path (`github.com/ai-agent-assembly/go-sdk`) — Go module
// paths are case-sensitive and the SDK imports its own internal packages under
// that exact spelling, so the casing must match or the internal-package import
// boundary check fails.
//
// The `replace` below points at the conventional sibling checkout (`../go-sdk`,
// four levels up from this module); the Python orchestrator
// (`tests/live/framework_drivers_go.py`) overrides it with `go mod edit -replace`
// in a temp build dir when the SDK lives elsewhere (e.g. `AASM_GO_SDK_DIR`), so
// the committed path is only the default.
module github.com/ai-agent-assembly/integration-tests/live/go-framework-driver

go 1.26.0

require (
	github.com/ai-agent-assembly/go-sdk v0.0.0
	github.com/tmc/langchaingo v0.1.14
)

require (
	github.com/cespare/xxhash/v2 v2.3.0 // indirect
	github.com/dlclark/regexp2 v1.12.0 // indirect
	github.com/google/uuid v1.6.0 // indirect
	github.com/oklog/ulid/v2 v2.1.1 // indirect
	github.com/pkoukk/tiktoken-go v0.1.8 // indirect
	go.opentelemetry.io/otel v1.44.0 // indirect
	go.opentelemetry.io/otel/trace v1.44.0 // indirect
	go.starlark.net v0.0.0-20260613233743-8ba36ccb83fb // indirect
	golang.org/x/net v0.56.0 // indirect
	golang.org/x/sys v0.46.0 // indirect
	golang.org/x/text v0.38.0 // indirect
	google.golang.org/genproto/googleapis/rpc v0.0.0-20260610212136-7ab31c22f7ad // indirect
	google.golang.org/grpc v1.81.1 // indirect
	google.golang.org/protobuf v1.36.11 // indirect
	gopkg.in/yaml.v3 v3.0.1 // indirect
)

replace github.com/ai-agent-assembly/go-sdk => ../../../../../../go-sdk
