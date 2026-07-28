# Contributing

Thanks for your interest. Bug reports, documentation fixes and features are all
welcome.

## Getting set up

```bash
git clone https://github.com/<you>/AI-ML-Based-traffic-management-system.git
cd AI-ML-Based-traffic-management-system

# Backend (Python 3.11+)
cd backend
python -m venv .venv && source .venv/bin/activate
pip install torch torchvision --index-url https://download.pytorch.org/whl/cpu
pip install -r requirements.txt -r requirements-dev.txt
pytest

# Frontend (Node 20.19+)
cd ../frontend
npm install
npm test
```

The full backend suite runs in about ten seconds and needs no model weights or
GPU — the detector is stubbed throughout.

## Before opening a pull request

```bash
# Backend
cd backend
pytest                              # all tests pass
ruff check app && ruff format app   # lint and format
mypy app                            # type check

# Frontend
cd frontend
npm run type-check && npm run lint && npm test && npm run build
```

## What we look for

**Tests that describe behaviour.** A test name should say what the system does,
not which method was called. `test_green_is_capped_so_one_approach_cannot_starve_the_others`
tells a reader why the cap exists; `test_max_green` does not.

**Comments that explain why.** The code says what it does. A comment earns its
place by explaining a decision that is not obvious — a trade-off, a constraint,
a rejected alternative.

**Honesty about limits.** If a feature is approximate, say so in the docstring
and in the API response. The impact model returns its assumptions with every
estimate for exactly this reason. We would rather ship a caveated number than a
confident wrong one.

## Areas that especially need help

| Area | Why it matters |
|---|---|
| **Emergency vehicle detection** | Currently pre-emption must be raised via the API. A custom-trained ambulance/fire-engine class would let it be detected visually. |
| **Camera calibration** | Speed estimation needs `metres_per_pixel` supplied by hand. A calibration helper from known reference points would remove that step. |
| **Non-overhead camera geometry** | Lane assignment assumes an overhead view with north at the top. Configurable sector geometry would widen the deployable set enormously. |
| **NTCIP adapter** | Most commercial cabinet controllers speak NTCIP 1202. An adapter would make this deployable against existing hardware. |
| **Turning movements** | The controller treats each approach as one movement. Separate left/right phases are the next real step in fidelity. |
| **Validation against field data** | If you have before/after travel-time data from a real deployment, it would be genuinely valuable. |

## Safety-critical changes

Changes to `adaptive_traffic_manager.py` need particular care. The controller's
core guarantee is that conflicting movements never hold green simultaneously,
and that every green is separated from the conflicting green by yellow and
all-red clearance.

If you touch the phase machine:

- Keep `_aspects_for()` the single place that decides what each head shows.
- Never introduce a path that sets a signal's state outside a phase transition.
- Run the invariant tests in `tests/unit/test_traffic_controller.py`, and add
  one for any new phase or transition you introduce.

If a change makes those tests harder to satisfy, that is usually the design
telling you something.

## Commit messages

Present tense, and say what changed and why:

```
Extend green when demand arrives mid-phase

Vehicles joining a queue after the green started previously waited a full
cycle. The controller now grants extra green up to the configured maximum.
```

## Reporting bugs

Include:

- What you expected and what happened
- The `request_id` from the error response, if there is one
- Relevant output from `GET /api/v1/system/info` and `GET /health`
- Version, deployment method, and whether detection or manual counts were in use

## Security

Do not open a public issue for a vulnerability. See [`SECURITY.md`](SECURITY.md).

## Licence

Contributions are accepted under the [MIT Licence](LICENSE).
