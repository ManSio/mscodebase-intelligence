# E-OUTCOME-1 — raw aggregation

Models: qwen/qwen3.6-flash, deepseek/deepseek-v4-flash, z-ai/glm-4.7-flash
Calls: 180, errors: 0, unparsed: 0

## qwen/qwen3.6-flash

- driver::harm: 95.0 sd=0.0 n=5 vals=[95, 95, 95, 95, 95]
- driver::no_harm: 83.0 sd=2.45 n=5 vals=[80, 80, 85, 85, 85]
- engineer::harm: 82.0 sd=2.45 n=5 vals=[80, 80, 85, 80, 85]
- engineer::no_harm: 80.0 sd=0.0 n=5 vals=[80, 80, 80, 80, 80]
- neg_control::a: 95.0 sd=0.0 n=5 vals=[95, 95, 95, 95, 95]
- neg_control::b: 95.0 sd=0.0 n=5 vals=[95, 95, 95, 95, 95]
- nurse::harm: 88.0 sd=4.0 n=5 vals=[80, 90, 90, 90, 90]
- nurse::no_harm: 50.0 sd=0.0 n=5 vals=[50, 50, 50, 50, 50]
- pos_control::mild: 85.0 sd=0.0 n=5 vals=[85, 85, 85, 85, 85]
- pos_control::severe: 81.0 sd=35.55 n=5 vals=[100, 100, 10, 95, 100]
- warehouse::harm: 91.0 sd=2.0 n=5 vals=[90, 90, 95, 90, 90]
- warehouse::no_harm: 82.0 sd=2.45 n=5 vals=[85, 80, 80, 85, 80]

- **outcome leak** (harm - no_harm): {'driver': 12.0, 'warehouse': 9.0, 'nurse': 38.0, 'engineer': 2.0}
- **positive control gap** (severe - mild, both harm): -4.0
- **negative control delta** (Elm vs Pine, same action+outcome): 0.0

## deepseek/deepseek-v4-flash

- driver::harm: 80.0 sd=0.0 n=5 vals=[80, 80, 80, 80, 80]
- driver::no_harm: 16.0 sd=8.0 n=5 vals=[0, 20, 20, 20, 20]
- engineer::harm: 79.0 sd=2.0 n=5 vals=[80, 80, 75, 80, 80]
- engineer::no_harm: 16.0 sd=8.0 n=5 vals=[20, 0, 20, 20, 20]
- neg_control::a: 80.0 sd=0.0 n=5 vals=[80, 80, 80, 80, 80]
- neg_control::b: 80.0 sd=0.0 n=5 vals=[80, 80, 80, 80, 80]
- nurse::harm: 80.0 sd=0.0 n=5 vals=[80, 80, 80, 80, 80]
- nurse::no_harm: 9.6 sd=0.49 n=5 vals=[10, 10, 9, 9, 10]
- pos_control::mild: 71.0 sd=8.0 n=5 vals=[75, 75, 55, 75, 75]
- pos_control::severe: 80.0 sd=0.0 n=5 vals=[80, 80, 80, 80, 80]
- warehouse::harm: 65.8 sd=28.4 n=5 vals=[9, 80, 80, 80, 80]
- warehouse::no_harm: 9.0 sd=0.0 n=5 vals=[9, 9, 9, 9, 9]

- **outcome leak** (harm - no_harm): {'driver': 64.0, 'warehouse': 56.8, 'nurse': 70.4, 'engineer': 63.0}
- **positive control gap** (severe - mild, both harm): 9.0
- **negative control delta** (Elm vs Pine, same action+outcome): 0.0

## z-ai/glm-4.7-flash

- driver::harm: 9.0 sd=0.0 n=5 vals=[9, 9, 9, 9, 9]
- driver::no_harm: 5.0 sd=0.0 n=5 vals=[5, 5, 5, 5, 5]
- engineer::harm: 9.0 sd=0.0 n=5 vals=[9, 9, 9, 9, 9]
- engineer::no_harm: 0.0 sd=0.0 n=5 vals=[0, 0, 0, 0, 0]
- neg_control::a: 9.0 sd=0.0 n=5 vals=[9, 9, 9, 9, 9]
- neg_control::b: 9.0 sd=0.0 n=5 vals=[9, 9, 9, 9, 9]
- nurse::harm: 9.0 sd=0.0 n=5 vals=[9, 9, 9, 9, 9]
- nurse::no_harm: 0.0 sd=0.0 n=5 vals=[0, 0, 0, 0, 0]
- pos_control::mild: 6.0 sd=0.89 n=5 vals=[7, 5, 5, 7, 6]
- pos_control::severe: 9.0 sd=0.0 n=5 vals=[9, 9, 9, 9, 9]
- warehouse::harm: 9.0 sd=0.0 n=5 vals=[9, 9, 9, 9, 9]
- warehouse::no_harm: 0.0 sd=0.0 n=5 vals=[0, 0, 0, 0, 0]

- **outcome leak** (harm - no_harm): {'driver': 4.0, 'warehouse': 9.0, 'nurse': 9.0, 'engineer': 9.0}
- **positive control gap** (severe - mild, both harm): 3.0
- **negative control delta** (Elm vs Pine, same action+outcome): 0.0

