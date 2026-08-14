#!/usr/bin/env bash
# Regenerates app/xray_proto/*_pb2*.py from proto/*.proto. Run from xray-agent/ after
# changing anything under proto/. Requires grpcio-tools (installed via the `dev` extra
# — see pyproject.toml). See docs/xray-agent.md's "gRPC integration" section for what
# these proto files are and why they're a trimmed subset of xray-core's own.
set -euo pipefail
cd "$(dirname "$0")/.."

python -m grpc_tools.protoc \
  --proto_path=proto \
  --python_out=app/xray_proto \
  --grpc_python_out=app/xray_proto \
  --pyi_out=app/xray_proto \
  proto/typed_message.proto proto/user.proto proto/vless_account.proto proto/command.proto

# protoc's Python codegen emits bare sibling imports (e.g. `import user_pb2`), which
# only work if app/xray_proto/ is on sys.path directly. Rewriting them to
# package-relative imports lets this generated code live as a normal subpackage
# (app.xray_proto) instead of needing a sys.path hack at import time.
cd app/xray_proto
sed -i.bak -E 's/^import ([a-z_]+_pb2) as/from app.xray_proto import \1 as/' ./*_pb2*.py
rm -f ./*.bak

# Only command.proto declares a service — the plain-message protos produce an
# essentially empty *_pb2_grpc.py that nothing imports; drop it to avoid clutter. The
# .pyi stubs are kept for every message proto (not just command's) — app/xray/
# handler_client.py constructs User/Account/TypedMessage directly, and mypy can only
# see those as real attributes (BuildTopDescriptorsAndMessages populates them
# dynamically at runtime, invisible to static analysis) via their .pyi stub.
rm -f typed_message_pb2_grpc.py user_pb2_grpc.py vless_account_pb2_grpc.py
rm -rf __pycache__

echo "Regenerated app/xray_proto/. Review the diff before committing."
