# E-OUTCOME-1 — raw aggregation

Models: qwen2.5-3b-instruct
Calls: 60, errors: 0, unparsed: 0

## qwen2.5-3b-instruct

- driver::harm: 8.0 sd=0.0 n=5 vals=[8, 8, 8, 8, 8]
- driver::no_harm: 2.0 sd=0.0 n=5 vals=[2, 2, 2, 2, 2]
- engineer::harm: 9.0 sd=0.0 n=5 vals=[9, 9, 9, 9, 9]
- engineer::no_harm: 2.0 sd=0.0 n=5 vals=[2, 2, 2, 2, 2]
- neg_control::a: 8.0 sd=0.0 n=5 vals=[8, 8, 8, 8, 8]
- neg_control::b: 8.0 sd=0.0 n=5 vals=[8, 8, 8, 8, 8]
- nurse::harm: 9.0 sd=0.0 n=5 vals=[9, 9, 9, 9, 9]
- nurse::no_harm: 2.0 sd=0.0 n=5 vals=[2, 2, 2, 2, 2]
- pos_control::mild: 8.0 sd=0.0 n=5 vals=[8, 8, 8, 8, 8]
- pos_control::severe: 8.0 sd=0.0 n=5 vals=[8, 8, 8, 8, 8]
- warehouse::harm: 9.0 sd=0.0 n=5 vals=[9, 9, 9, 9, 9]
- warehouse::no_harm: 2.0 sd=0.0 n=5 vals=[2, 2, 2, 2, 2]

- **outcome leak** (harm - no_harm): {'driver': 6.0, 'warehouse': 7.0, 'nurse': 7.0, 'engineer': 7.0}
- **positive control gap** (severe - mild, both harm): 0.0
- **negative control delta** (Elm vs Pine, same action+outcome): 0.0

