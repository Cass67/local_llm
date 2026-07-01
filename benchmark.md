# Benchmark Type Integration Progress

## Goal
Add terminal-bench and swe-bench as selectable benchmark options in the web UI with:
- Real-time progress viewing
- Results stored in the leaderboard
- Modular design where each benchmark runs in its own container for future extensibility

## Constraints & Preferences
- **Ponytail philosophy**: Minimal, modular, and extensible code
- Each benchmark should run in its own container for security and isolation
- Backward compatible with existing standard benchmarks
- All operations run on "ubt26" remote Ubuntu server via SSH
- Model API runs on `192.168.2.1:3100/v1` - benchmark endpoints must point here
- **Internet Access**: ubt26 DOES have internet access for package downloads and Docker pulls

## Architecture Decisions

### 1. Modular Runner Design
Each benchmark type inherits from `BaseBenchmarkRunner` and implements `run()` method:
- `TerminalBenchRunner` (container/backend/benchmarks/terminal_bench.py)
- `SwebenchRunner` (container/backend/benchmarks/swe_bench.py)

### 2. Database Schema
Added `benchmark_type` column to existing `benchmark_runs` table with default `'standard'` for backward compatibility.

### 3. API Approach
- `/api/benchmark/types` - List available benchmark types
- `/api/benchmark/runs/{type}` - Run specific benchmark type
- `/api/benchmark/runs` - Run standard benchmarks (backward compatible)
- All endpoints accept `endpoint_base_url` for model configuration

### 4. Containerization Strategy
- Initial plan: Separate worker containers for terminal-bench and swe-bench
- Revised: Run benchmarks directly in main container using subprocess to call benchmark tools
- Both frameworks (terminal-bench, swebench) use their own Docker infrastructure
- Main container mounts Docker socket for nested container spawning

## Implementation Status

### ✅ Completed

#### Backend Changes
- [x] Extended data model with `benchmark_type` column
- [x] Created `BaseBenchmarkRunner` in `benchmarks/base.py`
- [x] Implemented `TerminalBenchRunner` using actual Terminal-Bench framework
- [x] Implemented `SwebenchRunner` using actual SWE-bench framework
- [x] Added API endpoints (`/api/benchmark/types`, `/api/benchmark/runs/{type}`)
- [x] Updated backend routes to accept `benchmark_type` filter
- [x] Fixed test client issue in `test_benchmark_types.py`
- [x] Removed `extra_data` from runner outputs (not in schema)
- [x] Added `endpoint_base_url` to runner execution and storage
- [x] Fixed SQL syntax error in summary method (two WHERE → AND clause)

#### Docker Setup
- [x] Created Dockerfiles for worker services (later replaced by direct execution)
- [x] Updated main `Dockerfile` to install `terminal-bench` and `swebench` packages
- [x] Created `docker-compose.yml` with host networking
- [x] Fixed YAML syntax error (duplicate volumes section)
- [x] Replaced port mappings with `network_mode: host`

#### Import Structure
- [x] Updated all imports from `backend.benchmarks` to `container.backend.benchmarks`
- [x] Removed old `benchmarks/` directory at repo root (caused import conflicts)
- [x] Created necessary directories on ubt26 (`/state/runs/clusters`, `/state/active_profiles`, `/state/models_cache`, `/models`)

#### Testing & Verification
- [x] Successfully tested terminal-bench: `POST /api/benchmark/runs/terminal-bench` with `echo hello`
- [x] Successfully tested swe-bench: `POST /api/benchmark/runs/swe-bench` with mock response
- [x] Verified database storage with `benchmark_type` field
- [x] Verified filtering by benchmark type works correctly
- [x] Confirmed fresh UI build at `~/local_llm/container/ui-dist/`

#### Frontend Changes
- [x] Added `BenchmarkType` interface to TypeScript
- [x] Created `listBenchmarkTypes` and `runBenchmarkByType` functions
- [x] Extended `BenchmarkRun` with `benchmark_type`
- [x] Updated `Benchmarks.svelte` component:
  - Added benchmark type selector in hero section
  - Modified run execution to use either standard or type-specific API
  - Added filter dropdown for benchmark type
  - Added "Type" column to history table
  - Created separate leaderboard section with tabs for each benchmark type
  - Updated trend charts to show data for selected type

### ⚠️ Current Issues

#### Port 3100 Serving Old Build
- **Problem**: Port 3100 is serving an old build from `benchmarks/backend/main.py` instead of the new build from `container.backend.main:app`
- **Symptom**: Accessing `http://192.168.2.1:3100/ui` shows old UI without benchmark type selector
- **Root Cause**: Two separate backend implementations exist; old one at `benchmarks/backend/` is being imported by default
- **Status**: Identified, working on fix

#### UI Build Synchronization
- **Problem**: Port 3105 serves fresh build (`index-J5DRHp5D.js`), port 3100 serves old build (`index-B7AMfslw.js`)
- **Evidence**: `diff` of index.html shows different JS/CSS references
- **Impact**: Users accessing port 3100 don't see new features

### 🔄 Current Work
1. Kill old server on port 3100 (running from `benchmarks/backend/main.py`)
2. Start new server on port 3100 (from `container.backend.main:app`)
3. Verify benchmark type selector appears at `http://192.168.2.1:3100/ui/#/benchmarks`
4. Ensure all model API endpoints work with benchmark execution

## Next Steps
1. **Immediate**: Fix port 3100 to serve new UI (stop old server, start correct one)
2. **Verification**: Test full benchmark execution flow through web UI
3. **Documentation**: Update README with instructions for adding new benchmark types
4. **Cleanup**: Remove deprecated `benchmarks/backend/` directory

## Key Files
- **Backend**: `container/backend/benchmarks/base.py`, `terminal_bench.py`, `swe_bench.py`
- **Routes**: `container/backend/routes/benchmark.py`
- **Database**: `container/backend/benchmark_store.py`
- **Frontend**: `ui/src/routes/Benchmarks.svelte`, `ui/src/lib/benchmarkApi.ts`, `ui/src/lib/benchmarkMetrics.ts`
- **Docker**: `container/Dockerfile`, `docker-compose.yml`

## Notes
- Test files: `container/tests/test_benchmark_types.py` - passing after fixes
- Database state: Two benchmark runs stored (1 terminal-bench, 1 swe-bench) with all metrics captured
- Model configuration: Need to create endpoint pointing to `192.168.2.1:3100/v1` if not already configured
- UI caching: Caddy reverse proxy may cache old builds; clear cache after switching servers
