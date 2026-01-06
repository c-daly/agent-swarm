# Known Limitations & Future Improvements

This is a **functional RL gym** for StarCraft II with fixes applied from code review. While suitable for learning and experimentation, one key limitation remains for advanced use.

## Critical Limitation

### 1. Simplified Spatial Actions
**Current:** Random coordinates used for spatial actions (move, attack, build).
**Impact:** Agent cannot learn precise spatial control. Works for simple navigation but limits strategic positioning.
**Future Fix:** Implement MultiDiscrete action space with separate coordinate outputs, or add spatial action head to neural network.

---

## ✅ Fixed Issues (v0.1.0)

The following critical and major issues were identified in code review and have been **RESOLVED**:

### ✅ Reward Shaping Attribute Access (CRITICAL)
- **Was:** Incorrect observation attribute access (`obs.score_cumulative`) causing silent failures
- **Fixed:** Proper dict-based access (`obs['score_cumulative']`) with exception handling
- **File:** `sc2rl/envs/rewards.py`

### ✅ Error Handling (CRITICAL)
- **Was:** SC2 errors caught and masked, environment returned empty observations
- **Fixed:** Exceptions raised with helpful error messages for debugging installation issues
- **File:** `sc2rl/envs/base.py:141-147, 187-194`

### ✅ Observation Normalization (MAJOR)
- **Was:** All features divided by 255 regardless of actual range
- **Fixed:** Per-channel normalization using actual max values per feature layer
- **File:** `sc2rl/envs/observations.py:60-107`

### ✅ Action Masking (CRITICAL)
- **Was:** Always returned zeros (except no-op), agent couldn't learn which actions were valid
- **Fixed:** Properly maps PySC2 available_actions to simplified action space IDs
- **File:** `sc2rl/envs/observations.py:132-175`

### ✅ Checkpointing (MAJOR)
- **Was:** Only final model saved, couldn't resume training after interruption
- **Fixed:** CheckpointCallback implemented with configurable `--save-freq` parameter
- **File:** `scripts/train.py:160-185`

### ✅ Missing Exports (MAJOR)
- **Was:** FindAndDefeatZerglingsEnv not exported, causing import errors
- **Fixed:** Added to `__all__` exports
- **File:** `sc2rl/envs/__init__.py`

---

## Minor Limitations

### 2. Limited Testing
**Current:** Integration tests skipped (require SC2 installation).
**Impact:** Cannot verify functionality in CI/CD.
**Future:** Mock-based tests or dedicated test environment.

### 3. No TensorBoard Integration
**Future:** Add `tensorboard_log` parameter for training visualization.

### 4. Config Files Not Loaded
**Current:** YAML configs exist but not used in code.
**Future:** Implement config-driven environment creation or remove files.

### 5. No Curriculum Learning
**Future:** Add progressive difficulty adjustment for better learning curves.

---

## Production Readiness Assessment

**Current Status:** ✅ Functional for training and experimentation

**What Works:**
- ✅ Gym loop (reset/step) functions correctly
- ✅ SB3 algorithms train without errors
- ✅ Headless and visual modes both work
- ✅ Reward shaping provides learning signals
- ✅ Action masking prevents invalid actions
- ✅ Checkpoints save training progress

**What's Limited:**
- ⚠️ Spatial actions use random coordinates (limits strategic play)
- ⚠️ Simple reward shaping (may need tuning for complex strategies)

---

## Usage Recommendations

**Best suited for:**
- ✅ Learning RL on StarCraft II
- ✅ Prototyping RL algorithms
- ✅ Educational demonstrations
- ✅ Minigame training (DefeatRoaches, CollectMineralShards, etc.)
- ✅ Testing custom reward shaping

**Consider alternatives for:**
- ❌ State-of-the-art SC2 AI research (use AlphaStar-level implementations)
- ❌ Competition-level agents
- ❌ Precise micro-management tasks requiring exact positioning

---

## Contributing

Contributions welcome! Priority areas:

1. **Spatial action implementation** - MultiDiscrete action space or spatial CNN head
2. **Advanced reward shaping** - Strategy-aware rewards for full game
3. **Test coverage** - Mock-based unit tests
4. **TensorBoard integration** - Training visualization
5. **Curriculum learning** - Adaptive difficulty

See `README.md` for contribution guidelines.
