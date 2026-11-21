# load-before-ts: per steady VU level

| VUs (steady) | seconds | requests | req/s | errors | error % | p50 | p95 | p99 |
|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| 5 | 60 | 235 | 3.9 | 0 | 0.0% | 219 ms | 898 ms | 1.0 s |
| 10 | 60 | 469 | 7.8 | 0 | 0.0% | 168 ms | 1.0 s | 1.7 s |
| 25 | 60 | 566 | 9.4 | 0 | 0.0% | 1.5 s | 4.8 s | 5.1 s |
| 50 | 60 | 616 | 10.3 | 0 | 0.0% | 3.5 s | 7.3 s | 8.2 s |

HTTP statuses: 200: 2639 (100.0%)
