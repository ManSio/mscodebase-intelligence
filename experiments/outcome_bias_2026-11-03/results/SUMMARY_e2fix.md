# E-OUTCOME-1 — raw aggregation

Models: qwen/qwen3.6-flash, deepseek/deepseek-v4-flash, z-ai/glm-4.7-flash
Calls: 180, errors: 0, unparsed: 0

## qwen/qwen3.6-flash

- driver::harm: 95.0 sd=0.0 n=5 vals=[95, 95, 95, 95, 95]
- driver::no_harm: 82.0 sd=2.45 n=5 vals=[80, 85, 85, 80, 80]
- engineer::harm: 87.0 sd=2.45 n=5 vals=[85, 90, 90, 85, 85]
- engineer::no_harm: 81.0 sd=2.0 n=5 vals=[85, 80, 80, 80, 80]
- neg_control::a: 95.0 sd=0.0 n=5 vals=[95, 95, 95, 95, 95]
- neg_control::b: 95.0 sd=0.0 n=5 vals=[95, 95, 95, 95, 95]
- nurse::harm: 91.0 sd=2.0 n=5 vals=[90, 90, 90, 90, 95]
- nurse::no_harm: 50.0 sd=0.0 n=5 vals=[50, 50, 50, 50, 50]
- pos_control::mild: 95.0 sd=0.0 n=5 vals=[95, 95, 95, 95, 95]
- pos_control::severe: 100.0 sd=0.0 n=5 vals=[100, 100, 100, 100, 100]
- warehouse::harm: 95.0 sd=0.0 n=5 vals=[95, 95, 95, 95, 95]
- warehouse::no_harm: 82.0 sd=2.45 n=5 vals=[85, 80, 85, 80, 80]

- **outcome leak** (harm - no_harm): {'driver': 13.0, 'warehouse': 13.0, 'nurse': 41.0, 'engineer': 6.0}
- **positive control gap** (severe - mild, both harm): 5.0
- **negative control delta** (Elm vs Pine, same action+outcome): 0.0

## deepseek/deepseek-v4-flash

- driver::harm: 100.0 sd=0.0 n=5 vals=[100, 100, 100, 100, 100]
- driver::no_harm: 100.0 sd=0.0 n=5 vals=[100, 100, 100, 100, 100]
- engineer::harm: 80.0 sd=0.0 n=5 vals=[80, 80, 80, 80, 80]
- engineer::no_harm: 60.0 sd=48.99 n=5 vals=[0, 100, 0, 100, 100]
- neg_control::a: 100.0 sd=0.0 n=5 vals=[100, 100, 100, 100, 100]
- neg_control::b: 100.0 sd=0.0 n=5 vals=[100, 100, 100, 100, 100]
- nurse::harm: 100.0 sd=0.0 n=5 vals=[100, 100, 100, 100, 100]
- nurse::no_harm: 31.0 sd=22.0 n=5 vals=[20, 75, 20, 20, 20]
- pos_control::mild: 100.0 sd=0.0 n=5 vals=[100, 100, 100, 100, 100]
- pos_control::severe: 100.0 sd=0.0 n=5 vals=[100, 100, 100, 100, 100]
- warehouse::harm: 100.0 sd=0.0 n=5 vals=[100, 100, 100, 100, 100]
- warehouse::no_harm: 100.0 sd=0.0 n=5 vals=[100, 100, 100, 100, 100]

- **outcome leak** (harm - no_harm): {'driver': 0.0, 'warehouse': 0.0, 'nurse': 69.0, 'engineer': 20.0}
- **positive control gap** (severe - mild, both harm): 0.0
- **negative control delta** (Elm vs Pine, same action+outcome): 0.0

## z-ai/glm-4.7-flash

- driver::harm: 92.0 sd=4.0 n=5 vals=[90, 90, 90, 90, 100]
- driver::no_harm: 20.0 sd=0.0 n=5 vals=[20, 20, 20, 20, 20]
- engineer::harm: 100.0 sd=0.0 n=5 vals=[100, 100, 100, 100, 100]
- engineer::no_harm: 0.0 sd=0.0 n=5 vals=[0, 0, 0, 0, 0]
- neg_control::a: 100.0 sd=0.0 n=5 vals=[100, 100, 100, 100, 100]
- neg_control::b: 100.0 sd=0.0 n=5 vals=[100, 100, 100, 100, 100]
- nurse::harm: 100.0 sd=0.0 n=5 vals=[100, 100, 100, 100, 100]
- nurse::no_harm: 0.0 sd=0.0 n=5 vals=[0, 0, 0, 0, 0]
- pos_control::mild: 38.0 sd=9.8 n=5 vals=[30, 30, 50, 50, 30]
- pos_control::severe: 100.0 sd=0.0 n=5 vals=[100, 100, 100, 100, 100]
- warehouse::harm: 100.0 sd=0.0 n=5 vals=[100, 100, 100, 100, 100]
- warehouse::no_harm: 0.0 sd=0.0 n=5 vals=[0, 0, 0, 0, 0]

- **outcome leak** (harm - no_harm): {'driver': 72.0, 'warehouse': 100.0, 'nurse': 100.0, 'engineer': 100.0}
- **positive control gap** (severe - mild, both harm): 62.0
- **negative control delta** (Elm vs Pine, same action+outcome): 0.0

