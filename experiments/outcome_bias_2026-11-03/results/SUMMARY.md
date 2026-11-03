# E-OUTCOME-1 — raw aggregation

Models: qwen/qwen3.6-flash, deepseek/deepseek-v4-flash, z-ai/glm-4.7-flash
Calls: 180, errors: 0, unparsed: 0

## qwen/qwen3.6-flash

- driver::harm: 9.0 sd=0.0 n=5 vals=[9, 9, 9, 9, 9]
- driver::no_harm: 8.6 sd=0.49 n=5 vals=[9, 9, 9, 8, 8]
- engineer::harm: 8.0 sd=0.0 n=5 vals=[8, 8, 8, 8, 8]
- engineer::no_harm: 7.0 sd=0.0 n=5 vals=[7, 7, 7, 7, 7]
- neg_control::a: 9.0 sd=0.0 n=5 vals=[9, 9, 9, 9, 9]
- neg_control::b: 9.0 sd=0.0 n=5 vals=[9, 9, 9, 9, 9]
- nurse::harm: 9.0 sd=0.0 n=5 vals=[9, 9, 9, 9, 9]
- nurse::no_harm: 4.4 sd=0.49 n=5 vals=[5, 4, 5, 4, 4]
- pos_control::mild: 8.2 sd=0.4 n=5 vals=[8, 8, 8, 9, 8]
- pos_control::severe: 9.0 sd=0.0 n=5 vals=[9, 9, 9, 9, 9]
- warehouse::harm: 9.0 sd=0.0 n=5 vals=[9, 9, 9, 9, 9]
- warehouse::no_harm: 7.8 sd=0.98 n=5 vals=[9, 7, 7, 9, 7]

- **outcome leak** (harm - no_harm): {'driver': 0.4, 'warehouse': 1.2, 'nurse': 4.6, 'engineer': 1.0}
- **positive control gap** (severe - mild, both harm): 0.8
- **negative control delta** (Elm vs Pine, same action+outcome): 0.0

## deepseek/deepseek-v4-flash

- driver::harm: 9.0 sd=0.0 n=5 vals=[9, 9, 9, 9, 9]
- driver::no_harm: 0.0 sd=0.0 n=5 vals=[0, 0, 0, 0, 0]
- engineer::harm: 9.0 sd=0.0 n=5 vals=[9, 9, 9, 9, 9]
- engineer::no_harm: 8.0 sd=0.0 n=5 vals=[8, 8, 8, 8, 8]
- neg_control::a: 9.0 sd=0.0 n=5 vals=[9, 9, 9, 9, 9]
- neg_control::b: 9.0 sd=0.0 n=5 vals=[9, 9, 9, 9, 9]
- nurse::harm: 9.0 sd=0.0 n=5 vals=[9, 9, 9, 9, 9]
- nurse::no_harm: 0.0 sd=0.0 n=5 vals=[0, 0, 0, 0, 0]
- pos_control::mild: 8.8 sd=0.4 n=5 vals=[9, 9, 9, 9, 8]
- pos_control::severe: 9.0 sd=0.0 n=5 vals=[9, 9, 9, 9, 9]
- warehouse::harm: 9.0 sd=0.0 n=5 vals=[9, 9, 9, 9, 9]
- warehouse::no_harm: 0.0 sd=0.0 n=5 vals=[0, 0, 0, 0, 0]

- **outcome leak** (harm - no_harm): {'driver': 9.0, 'warehouse': 9.0, 'nurse': 9.0, 'engineer': 1.0}
- **positive control gap** (severe - mild, both harm): 0.2
- **negative control delta** (Elm vs Pine, same action+outcome): 0.0

## z-ai/glm-4.7-flash

- driver::harm: 9.0 sd=0.0 n=5 vals=[9, 9, 9, 9, 9]
- driver::no_harm: 4.0 sd=0.0 n=5 vals=[4, 4, 4, 4, 4]
- engineer::harm: 9.0 sd=0.0 n=5 vals=[9, 9, 9, 9, 9]
- engineer::no_harm: 2.4 sd=2.15 n=5 vals=[5, 1, 0, 5, 1]
- neg_control::a: 9.0 sd=0.0 n=5 vals=[9, 9, 9, 9, 9]
- neg_control::b: 9.0 sd=0.0 n=5 vals=[9, 9, 9, 9, 9]
- nurse::harm: 9.0 sd=0.0 n=5 vals=[9, 9, 9, 9, 9]
- nurse::no_harm: 0.0 sd=0.0 n=5 vals=[0, 0, 0, 0, 0]
- pos_control::mild: 4.8 sd=0.4 n=5 vals=[5, 5, 5, 5, 4]
- pos_control::severe: 9.0 sd=0.0 n=5 vals=[9, 9, 9, 9, 9]
- warehouse::harm: 9.0 sd=0.0 n=5 vals=[9, 9, 9, 9, 9]
- warehouse::no_harm: 0.0 sd=0.0 n=5 vals=[0, 0, 0, 0, 0]

- **outcome leak** (harm - no_harm): {'driver': 5.0, 'warehouse': 9.0, 'nurse': 9.0, 'engineer': 6.6}
- **positive control gap** (severe - mild, both harm): 4.2
- **negative control delta** (Elm vs Pine, same action+outcome): 0.0

