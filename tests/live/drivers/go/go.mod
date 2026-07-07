// Live Go allow-path driver module (AAASM-3194).
//
// This is a standalone module so the driver compiles against the real go-sdk
// without pulling it into the integration repo's Python-only dependency set.
// The `replace` below points at the conventional sibling checkout
// (`../go-sdk`); the Python wrapper (`tests/live/sdk_drivers.py`) overrides it
// with `go mod edit -replace` in a temp build dir when the SDK lives elsewhere
// (e.g. `AASM_GO_SDK_DIR`), so the committed path is only the default.
module github.com/ai-agent-assembly/integration-tests/live/go-allow-driver

go 1.26.0

require github.com/ai-agent-assembly/go-sdk v0.0.0

require (
	github.com/cespare/xxhash/v2 v2.3.0 // indirect
	github.com/oklog/ulid/v2 v2.1.1 // indirect
	go.opentelemetry.io/otel v1.43.0 // indirect
	go.opentelemetry.io/otel/trace v1.43.0 // indirect
	golang.org/x/net v0.55.0 // indirect
	golang.org/x/sys v0.42.0 // indirect
	golang.org/x/text v0.34.0 // indirect
	google.golang.org/genproto/googleapis/rpc v0.0.0-20260226221140-a57be14db171 // indirect
	google.golang.org/grpc v1.81.1 // indirect
	google.golang.org/protobuf v1.36.11 // indirect
	gopkg.in/yaml.v3 v3.0.1 // indirect
)

replace github.com/ai-agent-assembly/go-sdk => ../../../../../go-sdk
