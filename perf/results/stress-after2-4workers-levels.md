# stress-after2-4workers: per steady VU level

| VUs (steady) | seconds | requests | req/s | errors | error % | p50 | p95 | p99 |
|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| 10 | 40 | 380 | 9.5 | 0 | 0.0% | 49 ms | 132 ms | 149 ms |
| 25 | 40 | 948 | 23.7 | 0 | 0.0% | 46 ms | 154 ms | 194 ms |
| 50 | 40 | 1855 | 46.4 | 0 | 0.0% | 57 ms | 251 ms | 369 ms |
| 100 | 40 | 3442 | 86.0 | 0 | 0.0% | 104 ms | 511 ms | 644 ms |
| 150 | 40 | 4372 | 109.3 | 0 | 0.0% | 255 ms | 1.0 s | 1.2 s |

HTTP statuses: 200: 17010 (100.0%)
