# Copyright 2026 github.com/ppetr
#
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
#     http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.

# Build from the repo root, not this directory - needs builder/ too
# (pyproject.toml's packages.find covers both):
#   docker build -t ai-math-container-agent -f agent/Dockerfile .
FROM python:3.12-slim

WORKDIR /app
COPY pyproject.toml ./
COPY builder ./builder
COPY agent ./agent
RUN pip install --no-cache-dir .

EXPOSE 8000
CMD ["uvicorn", "agent.main:build_app", "--factory", "--host", "0.0.0.0", "--port", "8000"]
