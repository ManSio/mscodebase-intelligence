# OOM Crash Timeline — Zed Editor

> **Source:** `Zed.log` (5018 lines, 10.07-11.07) + `Zed.log.old` (3911 lines, 08.07-10.07)
> **Compiled:** 2026-07-11
> **System RAM:** 15.4 GB (16 GB physical)

---

## General Statistics

| Metric | Value |
|---|---|
| **Total Restarts** | **22** (13 with `app_will_quit timeout` before restart) |
| **Period** | 2026-07-08 00:11 — 2026-07-11 09:20 (3.4 days) |
| **Zed Versions** | v1.9.0, v1.10.0, v1.10.1, v1.10.2 |
| **Peak Resident Memory** | **10 090 MiB** (≈10.1 GB) — 2026-07-09 06:22:43 |
| **Peak Virtual Memory** | **16 003 MiB** (≈16.0 GB) — 2026-07-09 06:23:13 |
| **Memory usage records** | 308 (Zed.log) + 464 (Zed.log.old) = **772 total** |
| **Peaks >3000 MB Resident** | 14 (Zed.log) + 23 (Zed.log.old) = **37 episodes** |
| **System RAM** | 15.4 GB available |
| **`window not found` errors** | 100+ (massively before each crash) |

---

## All Restarts Table (with pre-crash memory)

### From `Zed.log.old` (08.07 — 10.07)

| # | Date | Time | Version | Resident | Virtual | Reason |
|---|---|---|---|---|---|---|
| 1 | 08.07 | 00:11 | v1.9.0 | — | — | First launch |
| 2 | 08.07 | **02:38** | v1.9.0 | 712 MiB | 1469 MiB | **`app_will_quit timeout`** (hung during close) |
| 3 | 08.07 | 06:37 | v1.9.0 | 289 MiB | 1076 MiB | Night idle → manual restart |
| 4 | 09.07 | **06:42** | v1.10.0 | 976 MiB | 4212 MiB | **`app_will_quit timeout`** (after night with 10 GB peaks) |
| 5 | 09.07 | **22:12** | v1.10.0 | 1367 MiB | 3140 MiB | **`app_will_quit timeout`** |
| 6 | 09.07 | **22:22** | v1.10.0 | 668 MiB | 814 MiB | **`app_will_quit timeout`** |
| 7 | 09.07 | **22:30** | v1.10.0 | 609 MiB | 630 MiB | **`app_will_quit timeout`** |
| 8 | 10.07 | **07:44** | v1.10.1 | 709 MiB | 862 MiB | **`app_will_quit timeout`** |
| 9 | 10.07 | **07:49** | v1.10.1 | 575 MiB | 594 MiB | **`app_will_quit timeout`** |
| 10 | 10.07 | **07:59** | v1.10.1 | 632 MiB | 700 MiB | **`app_will_quit timeout`** |

### From `Zed.log` (10.07 — 11.07)

| # | Date | Time | Version | Resident | Virtual | Reason |
|---|---|---|---|---|---|---|
| 11 | 10.07 | **08:03** | v1.10.1 | 562 MiB | 571 MiB | **`app_will_quit timeout`** |
| 12 | 10.07 | **08:32** | v1.10.1 | 865 MiB | 1025 MiB | **`app_will_quit timeout`** |
| 13 | 10.07 | **08:34** | v1.10.1 | 553 MiB | 548 MiB | **`app_will_quit timeout`** |
| 14 | 10.07 | 15:16 | v1.10.1 | 365 MiB | 2067 MiB | Without `app_will_quit` (manual start after idle) |
| 15 | 10.07 | **15:17** | v1.10.2 | 660 MiB | 673 MiB | **`app_will_quit timeout`** |
| 16 | 10.07 | **17:20** | v1.10.2 | 634 MiB | 2294 MiB | **`app_will_quit timeout`** |
| 17 | 10.07 | 17:22 | v1.10.2 | 762 MiB | 765 MiB | Without `app_will_quit` (crash after 7406 MiB peak?) |
| 18 | 10.07 | **22:36** | v1.10.2 | 1954 MiB | 4706 MiB | **`app_will_quit timeout`** (highest resident before crash) |
| 19 | 10.07 | **22:55** | v1.10.2 | 453 MiB | 503 MiB | **`app_will_quit timeout`** |
| 20 | 11.07 | 09:20 | v1.10.2 | — | — | Current session |

---

## All Memory Usage Records from Log

<details>
<summary>Zed.log — 308 records (10.07 08:00 — 11.07 09:26)</summary>

```
2026-07-10T08:00:14  resident 581 MiB (+64 MiB),  virtual 599 MiB
2026-07-10T08:01:14  resident 669 MiB (+88 MiB),  virtual 737 MiB
2026-07-10T08:02:14  resident 571 MiB (-97 MiB),  virtual 581 MiB
2026-07-10T08:02:44  resident 680 MiB (+108 MiB), virtual 738 MiB
2026-07-10T08:03:14  resident 562 MiB (-118 MiB), virtual 571 MiB
2026-07-10T08:03:51  resident 53 MiB,             virtual 24 MiB     ← RESTART
2026-07-10T08:04:21  resident 515 MiB (+462 MiB), virtual 545 MiB
2026-07-10T08:08:21  resident 741 MiB (+225 MiB), virtual 866 MiB
2026-07-10T08:08:50  resident 558 MiB (-182 MiB), virtual 567 MiB
2026-07-10T08:10:20  resident 899 MiB (+340 MiB), virtual 1098 MiB
2026-07-10T08:10:50  resident 620 MiB (-279 MiB), virtual 711 MiB
2026-07-10T08:12:50  resident 964 MiB (+344 MiB), virtual 1201 MiB
2026-07-10T08:13:20  resident 2034 MiB (+1069 MiB), virtual 2675 MiB
2026-07-10T08:13:50  resident 1085 MiB (-948 MiB), virtual 1340 MiB
2026-07-10T08:14:20  resident 673 MiB (-412 MiB), virtual 772 MiB
2026-07-10T08:14:50  resident 1010 MiB (+336 MiB), virtual 1229 MiB
2026-07-10T08:15:50  resident 822 MiB (-187 MiB), virtual 962 MiB
2026-07-10T08:16:20  resident 734 MiB (-87 MiB), virtual 836 MiB
2026-07-10T08:17:20  resident 868 MiB (+133 MiB), virtual 1003 MiB
2026-07-10T08:17:50  resident 1158 MiB (+290 MiB), virtual 1344 MiB
2026-07-10T08:18:20  resident 1515 MiB (+356 MiB), virtual 1835 MiB
2026-07-10T08:18:50  resident 3090 MiB (+1575 MiB), virtual 3990 MiB   ← >3 GB
2026-07-10T08:19:21  resident 4344 MiB (+1253 MiB), virtual 5649 MiB   ← >3 GB
2026-07-10T08:19:51  resident 866 MiB (-3478 MiB), virtual 946 MiB
2026-07-10T08:20:51  resident 1104 MiB (+238 MiB), virtual 1267 MiB
2026-07-10T08:21:21  resident 889 MiB (-214 MiB), virtual 970 MiB
2026-07-10T08:31:48  resident 865 MiB (-24 MiB), virtual 1025 MiB
2026-07-10T08:32:07  resident 53 MiB,             virtual 24 MiB     ← RESTART
2026-07-10T08:32:36  resident 553 MiB (+500 MiB), virtual 548 MiB
2026-07-10T08:34:11  resident 53 MiB,             virtual 24 MiB     ← RESTART
2026-07-10T08:34:41  resident 557 MiB (+504 MiB), virtual 598 MiB
2026-07-10T08:39:11  resident 632 MiB (+74 MiB), virtual 749 MiB
2026-07-10T08:42:11  resident 754 MiB (+122 MiB), virtual 897 MiB
2026-07-10T08:44:11  resident 1077 MiB (+323 MiB), virtual 1224 MiB
2026-07-10T08:45:11  resident 920 MiB (-156 MiB), virtual 1074 MiB
2026-07-10T08:48:11  resident 1104 MiB (+183 MiB), virtual 1251 MiB
2026-07-10T08:48:41  resident 1318 MiB (+214 MiB), virtual 1462 MiB
2026-07-10T08:49:11  resident 1000 MiB (-318 MiB), virtual 1150 MiB
2026-07-10T08:59:11  resident 1007 MiB (+7 MiB), virtual 1165 MiB
2026-07-10T09:09:01  resident 1477 MiB (+470 MiB), virtual 1782 MiB
2026-07-10T09:10:01  resident 1061 MiB (-416 MiB), virtual 1242 MiB
2026-07-10T09:12:31  resident 1660 MiB (+599 MiB), virtual 1967 MiB
2026-07-10T09:13:31  resident 1201 MiB (-458 MiB), virtual 1407 MiB
2026-07-10T09:14:01  resident 2031 MiB (+830 MiB), virtual 2409 MiB   ← >2 GB
2026-07-10T09:14:31  resident 1148 MiB (-883 MiB), virtual 1331 MiB
2026-07-10T09:15:31  resident 1317 MiB (+169 MiB), virtual 1567 MiB
2026-07-10T09:16:01  resident 1163 MiB (-153 MiB), virtual 1395 MiB
2026-07-10T09:16:31  resident 1527 MiB (+363 MiB), virtual 1830 MiB
2026-07-10T09:17:01  resident 1169 MiB (-358 MiB), virtual 1401 MiB
2026-07-10T09:18:01  resident 1939 MiB (+770 MiB), virtual 2339 MiB
2026-07-10T09:18:31  resident 1205 MiB (-734 MiB), virtual 1439 MiB
2026-07-10T09:19:01  resident 1611 MiB (+405 MiB), virtual 1926 MiB
2026-07-10T09:19:31  resident 1214 MiB (-397 MiB), virtual 1446 MiB
2026-07-10T09:20:01  resident 1575 MiB (+360 MiB), virtual 1881 MiB
2026-07-10T09:20:31  resident 1313 MiB (-261 MiB), virtual 1557 MiB
2026-07-10T09:25:31  resident 1023 MiB (-290 MiB), virtual 1552 MiB
2026-07-10T09:28:01  resident 1905 MiB (+882 MiB), virtual 2644 MiB
2026-07-10T09:28:31  resident 1472 MiB (-433 MiB), virtual 2091 MiB
2026-07-10T09:29:01  resident 1065 MiB (-407 MiB), virtual 1628 MiB
2026-07-10T09:30:01  resident 2010 MiB (+945 MiB), virtual 2743 MiB   ← >2 GB
2026-07-10T09:30:31  resident 1057 MiB (-952 MiB), virtual 1699 MiB
2026-07-10T09:40:32  resident 935 MiB (-122 MiB), virtual 1901 MiB
2026-07-10T09:41:32  resident 1144 MiB (+208 MiB), virtual 2131 MiB
2026-07-10T09:42:02  resident 945 MiB (-198 MiB), virtual 1928 MiB
2026-07-10T09:52:02  resident 861 MiB (-84 MiB), virtual 1910 MiB
2026-07-10T10:00:32  resident 993 MiB (+132 MiB), virtual 2015 MiB
2026-07-10T10:02:02  resident 1102 MiB (+108 MiB), virtual 2133 MiB
2026-07-10T10:10:32  resident 976 MiB (-126 MiB), virtual 2071 MiB
2026-07-10T10:20:33  resident 975 MiB (+0 MiB), virtual 2070 MiB
2026-07-10T10:28:03  resident 1077 MiB (+102 MiB), virtual 2068 MiB
2026-07-10T10:35:33  resident 951 MiB (-126 MiB), virtual 2068 MiB
2026-07-10T10:45:33  resident 948 MiB (-2 MiB), virtual 2067 MiB
2026-07-10T10:46:03  resident 825 MiB (-122 MiB), virtual 2067 MiB
2026-07-10T10:51:03  resident 642 MiB (-183 MiB), virtual 2067 MiB
2026-07-10T10:56:03  resident 568 MiB (-74 MiB), virtual 2067 MiB
2026-07-10T11:01:04  resident 407 MiB (-160 MiB), virtual 2067 MiB
2026-07-10T11:11:04  resident 365 MiB (-42 MiB), virtual 2067 MiB
2026-07-10T15:16:34  resident 66 MiB,             virtual 24 MiB     ← RESTART
2026-07-10T15:17:04  resident 660 MiB (+593 MiB), virtual 673 MiB
2026-07-10T15:17:51  resident 53 MiB,             virtual 24 MiB     ← RESTART
2026-07-10T15:18:21  resident 634 MiB (+581 MiB), virtual 633 MiB
2026-07-10T15:22:51  resident 798 MiB (+163 MiB), virtual 811 MiB
2026-07-10T15:23:51  resident 694 MiB (-103 MiB), virtual 703 MiB
2026-07-10T15:33:51  resident 1459 MiB (+764 MiB), virtual 1557 MiB
2026-07-10T15:34:21  resident 981 MiB (-477 MiB), virtual 1043 MiB
2026-07-10T15:34:51  resident 787 MiB (-194 MiB), virtual 837 MiB
2026-07-10T15:44:51  resident 839 MiB (+52 MiB), virtual 1001 MiB
2026-07-10T15:47:51  resident 500 MiB (-339 MiB), virtual 1034 MiB
2026-07-10T15:49:51  resident 601 MiB (+100 MiB), virtual 1136 MiB
2026-07-10T15:55:52  resident 673 MiB (+72 MiB), virtual 1222 MiB
2026-07-10T16:02:52  resident 558 MiB (-115 MiB), virtual 1175 MiB
2026-07-10T16:09:22  resident 808 MiB (+250 MiB), virtual 1710 MiB
2026-07-10T16:09:52  resident 640 MiB (-167 MiB), virtual 1364 MiB
2026-07-10T16:10:22  resident 565 MiB (-74 MiB), virtual 1223 MiB
2026-07-10T16:10:52  resident 723 MiB (+157 MiB), virtual 1522 MiB
2026-07-10T16:11:22  resident 595 MiB (-128 MiB), virtual 1271 MiB
2026-07-10T16:15:52  resident 959 MiB (+364 MiB), virtual 2026 MiB
2026-07-10T16:16:22  resident 617 MiB (-341 MiB), virtual 1340 MiB
2026-07-10T16:22:52  resident 504 MiB (-112 MiB), virtual 1354 MiB
2026-07-10T16:30:22  resident 573 MiB (+68 MiB), virtual 1508 MiB
2026-07-10T16:40:23  resident 542 MiB (-31 MiB), virtual 1450 MiB
2026-07-10T16:49:53  resident 621 MiB (+79 MiB), virtual 1566 MiB
2026-07-10T16:50:23  resident 550 MiB (-70 MiB), virtual 1458 MiB
2026-07-10T16:59:23  resident 682 MiB (+131 MiB), virtual 1660 MiB
2026-07-10T17:00:53  resident 1485 MiB (+802 MiB), virtual 3109 MiB   ← >3 GB virtual
2026-07-10T17:01:23  resident 641 MiB (-844 MiB), virtual 1576 MiB
2026-07-10T17:03:23  resident 876 MiB (+235 MiB), virtual 1985 MiB
2026-07-10T17:03:53  resident 690 MiB (-186 MiB), virtual 1641 MiB
2026-07-10T17:06:53  resident 1301 MiB (+610 MiB), virtual 2704 MiB
2026-07-10T17:07:23  resident 680 MiB (-620 MiB), virtual 1617 MiB
2026-07-10T17:07:53  resident 826 MiB (+146 MiB), virtual 2033 MiB
2026-07-10T17:08:23  resident 576 MiB (-250 MiB), virtual 1624 MiB
2026-07-10T17:13:54  resident 918 MiB (+341 MiB), virtual 2175 MiB
2026-07-10T17:14:24  resident 635 MiB (-282 MiB), virtual 1688 MiB
2026-07-10T17:15:54  resident 733 MiB (+97 MiB), virtual 1843 MiB
2026-07-10T17:16:24  resident 1064 MiB (+331 MiB), virtual 2409 MiB
2026-07-10T17:16:54  resident 1495 MiB (+430 MiB), virtual 3153 MiB   ← >3 GB virtual
2026-07-10T17:17:24  resident 3745 MiB (+2249 MiB), virtual 7074 MiB   ← >3 GB
2026-07-10T17:17:54  resident 1865 MiB (-1880 MiB), virtual 4535 MiB
2026-07-10T17:18:24  resident 254 MiB (-1610 MiB), virtual 1707 MiB
2026-07-10T17:18:54  resident 548 MiB (+294 MiB), virtual 2182 MiB
2026-07-10T17:19:54  resident 634 MiB (+86 MiB), virtual 2294 MiB
2026-07-10T17:20:18  resident 53 MiB,             virtual 24 MiB     ← RESTART
2026-07-10T17:20:48  resident 762 MiB (+709 MiB), virtual 765 MiB
2026-07-10T17:22:46  resident 50 MiB,             virtual 23 MiB     ← RESTART
2026-07-10T17:23:16  resident 739 MiB (+689 MiB), virtual 755 MiB
2026-07-10T17:23:46  resident 816 MiB (+77 MiB), virtual 863 MiB
2026-07-10T17:26:16  resident 1603 MiB (+786 MiB), virtual 2165 MiB
2026-07-10T17:26:46  resident 782 MiB (-821 MiB), virtual 810 MiB
2026-07-10T17:29:16  resident 1307 MiB (+525 MiB), virtual 1629 MiB
2026-07-10T17:29:46  resident 863 MiB (-444 MiB), virtual 875 MiB
2026-07-10T17:30:16  resident 1066 MiB (+203 MiB), virtual 1199 MiB
2026-07-10T17:30:46  resident 868 MiB (-197 MiB), virtual 883 MiB
2026-07-10T17:31:16  resident 998 MiB (+129 MiB), virtual 1089 MiB
2026-07-10T17:31:46  resident 873 MiB (-125 MiB), virtual 888 MiB
2026-07-10T17:38:46  resident 1307 MiB (+434 MiB), virtual 1581 MiB
2026-07-10T17:39:16  resident 884 MiB (-423 MiB), virtual 895 MiB
2026-07-10T17:49:17  resident 866 MiB (-17 MiB), virtual 886 MiB
2026-07-10T17:55:47  resident 1091 MiB (+224 MiB), virtual 1217 MiB
2026-07-10T17:56:17  resident 882 MiB (-208 MiB), virtual 889 MiB
2026-07-10T17:59:17  resident 988 MiB (+105 MiB), virtual 1118 MiB
2026-07-10T18:09:17  resident 980 MiB (-8 MiB), virtual 1095 MiB
2026-07-10T18:19:17  resident 1006 MiB (+26 MiB), virtual 1185 MiB
2026-07-10T18:22:47  resident 1149 MiB (+142 MiB), virtual 1424 MiB
2026-07-10T18:23:17  resident 1022 MiB (-127 MiB), virtual 1230 MiB
2026-07-10T18:25:47  resident 4345 MiB (+3322 MiB), virtual 6551 MiB   ← >3 GB
2026-07-10T18:26:17  resident 2954 MiB (-1390 MiB), virtual 4455 MiB
2026-07-10T18:26:47  resident 2429 MiB (-525 MiB), virtual 3635 MiB
2026-07-10T18:27:17  resident 1089 MiB (-1339 MiB), virtual 1466 MiB
2026-07-10T18:27:48  resident 3139 MiB (+2050 MiB), virtual 4721 MiB   ← >3 GB
2026-07-10T18:28:18  resident 1025 MiB (-2114 MiB), virtual 1374 MiB
2026-07-10T18:29:18  resident 1329 MiB (+303 MiB), virtual 1845 MiB
2026-07-10T18:29:48  resident 1014 MiB (-315 MiB), virtual 1369 MiB
2026-07-10T18:30:18  resident 1566 MiB (+552 MiB), virtual 2193 MiB
2026-07-10T18:30:48  resident 5100 MiB (+3533 MiB), virtual 7746 MiB   ← >3 GB
2026-07-10T18:31:18  resident 7406 MiB (+2306 MiB), virtual 11299 MiB   ← >3 GB
2026-07-10T18:31:48  resident 2233 MiB (-5172 MiB), virtual 3367 MiB
2026-07-10T18:32:18  resident 994 MiB (-1239 MiB), virtual 1477 MiB
2026-07-10T18:32:48  resident 4619 MiB (+3625 MiB), virtual 7015 MiB   ← >3 GB
2026-07-10T18:33:18  resident 7561 MiB (+2941 MiB), virtual 11406 MiB   ← >3 GB
2026-07-10T18:33:48  resident 1238 MiB (-6322 MiB), virtual 1851 MiB
2026-07-10T18:34:18  resident 1109 MiB (-128 MiB), virtual 1656 MiB
2026-07-10T18:34:48  resident 994 MiB (-115 MiB), virtual 1477 MiB
2026-07-10T18:36:48  resident 1109 MiB (+114 MiB), virtual 1631 MiB
2026-07-10T18:45:48  resident 1410 MiB (+301 MiB), virtual 2136 MiB
2026-07-10T18:46:18  resident 3091 MiB (+1681 MiB), virtual 4664 MiB   ← >3 GB
2026-07-10T18:46:48  resident 1029 MiB (-2062 MiB), virtual 1572 MiB
2026-07-10T18:56:48  resident 1040 MiB (+11 MiB), virtual 1650 MiB
2026-07-10T19:01:18  resident 1149 MiB (+108 MiB), virtual 1837 MiB
2026-07-10T19:02:48  resident 3730 MiB (+2581 MiB), virtual 5626 MiB   ← >3 GB
2026-07-10T19:03:18  resident 1087 MiB (-2642 MiB), virtual 1744 MiB
2026-07-10T19:06:18  resident 1642 MiB (+554 MiB), virtual 2581 MiB
2026-07-10T19:06:48  resident 1110 MiB (-531 MiB), virtual 1835 MiB
2026-07-10T19:09:48  resident 789 MiB (-320 MiB), virtual 2044 MiB
2026-07-10T19:10:18  resident 687 MiB (-102 MiB), virtual 1892 MiB
2026-07-10T19:11:49  resident 1160 MiB (+473 MiB), virtual 2573 MiB
2026-07-10T19:12:19  resident 1832 MiB (+671 MiB), virtual 3538 MiB   ← >3 GB virtual
2026-07-10T19:12:49  resident 689 MiB (-1143 MiB), virtual 1913 MiB
2026-07-10T19:14:49  resident 771 MiB (+82 MiB), virtual 2039 MiB
2026-07-10T19:18:49  resident 1244 MiB (+472 MiB), virtual 2699 MiB
2026-07-10T19:19:19  resident 737 MiB (-506 MiB), virtual 1996 MiB
2026-07-10T19:20:19  resident 1566 MiB (+829 MiB), virtual 3175 MiB   ← >3 GB virtual
2026-07-10T19:20:49  resident 1946 MiB (+379 MiB), virtual 3705 MiB   ← >3 GB virtual
2026-07-10T19:21:19  resident 731 MiB (-1214 MiB), virtual 1999 MiB
2026-07-10T19:22:19  resident 1265 MiB (+533 MiB), virtual 2738 MiB
2026-07-10T19:22:49  resident 746 MiB (-519 MiB), virtual 2013 MiB
2026-07-10T19:23:49  resident 871 MiB (+125 MiB), virtual 2198 MiB
2026-07-10T19:24:19  resident 1381 MiB (+510 MiB), virtual 2897 MiB
2026-07-10T19:24:49  resident 856 MiB (-525 MiB), virtual 2167 MiB
2026-07-10T19:25:19  resident 766 MiB (-90 MiB), virtual 2086 MiB
2026-07-10T19:27:49  resident 862 MiB (+96 MiB), virtual 2205 MiB
2026-07-10T19:28:19  resident 1016 MiB (+153 MiB), virtual 2405 MiB
2026-07-10T19:28:49  resident 1240 MiB (+224 MiB), virtual 2727 MiB
2026-07-10T19:29:19  resident 2348 MiB (+1108 MiB), virtual 4244 MiB   ← >2 GB
2026-07-10T19:29:49  resident 804 MiB (-1544 MiB), virtual 2146 MiB
2026-07-10T19:32:49  resident 978 MiB (+173 MiB), virtual 2405 MiB
2026-07-10T19:33:49  resident 859 MiB (-118 MiB), virtual 2246 MiB
2026-07-10T19:35:19  resident 2050 MiB (+1191 MiB), virtual 3828 MiB   ← >2 GB
2026-07-10T19:35:49  resident 3265 MiB (+1215 MiB), virtual 5451 MiB   ← >3 GB
2026-07-10T19:36:19  resident 832 MiB (-2433 MiB), virtual 2211 MiB
2026-07-10T19:44:19  resident 927 MiB (+95 MiB), virtual 2293 MiB
2026-07-10T19:54:20  resident 957 MiB (+29 MiB), virtual 2333 MiB
2026-07-10T20:04:20  resident 1046 MiB (+88 MiB), virtual 2512 MiB
2026-07-10T20:08:50  resident 1155 MiB (+109 MiB), virtual 2686 MiB
2026-07-10T20:10:50  resident 1401 MiB (+245 MiB), virtual 2699 MiB
2026-07-10T20:20:50  resident 1336 MiB (-64 MiB), virtual 2795 MiB
2026-07-10T20:30:50  resident 1364 MiB (+27 MiB), virtual 2834 MiB
2026-07-10T20:40:51  resident 1254 MiB (-109 MiB), virtual 2832 MiB
2026-07-10T20:50:51  resident 1286 MiB (+31 MiB), virtual 2889 MiB
2026-07-10T20:59:51  resident 1153 MiB (-132 MiB), virtual 3081 MiB
2026-07-10T21:09:51  resident 1169 MiB (+16 MiB), virtual 3097 MiB
2026-07-10T21:19:52  resident 1227 MiB (+58 MiB), virtual 3113 MiB
2026-07-10T21:29:52  resident 1244 MiB (+16 MiB), virtual 3216 MiB
2026-07-10T21:39:52  resident 1330 MiB (+86 MiB), virtual 3482 MiB
2026-07-10T21:49:52  resident 1424 MiB (+93 MiB), virtual 3728 MiB
2026-07-10T21:59:53  resident 1533 MiB (+109 MiB), virtual 3877 MiB
2026-07-10T22:09:53  resident 1637 MiB (+104 MiB), virtual 4115 MiB
2026-07-10T22:18:53  resident 1813 MiB (+175 MiB), virtual 4334 MiB
2026-07-10T22:28:53  resident 1954 MiB (+140 MiB), virtual 4706 MiB
2026-07-10T22:36:13  resident 51 MiB,             virtual 24 MiB     ← RESTART
2026-07-10T22:36:43  resident 281 MiB (+230 MiB), virtual 272 MiB
2026-07-10T22:39:13  resident 364 MiB (+83 MiB), virtual 384 MiB
2026-07-10T22:45:14  resident 453 MiB (+88 MiB), virtual 503 MiB
2026-07-10T22:55:03  resident 50 MiB,             virtual 24 MiB     ← RESTART
2026-07-10T22:55:33  resident 300 MiB (+249 MiB), virtual 317 MiB
2026-07-10T22:58:33  resident 367 MiB (+67 MiB), virtual 400 MiB
2026-07-10T23:01:33  resident 435 MiB (+68 MiB), virtual 473 MiB
2026-07-10T23:04:33  resident 535 MiB (+99 MiB), virtual 552 MiB
2026-07-10T23:11:33  resident 612 MiB (+76 MiB), virtual 712 MiB
2026-07-10T23:14:03  resident 701 MiB (+88 MiB), virtual 714 MiB
2026-07-10T23:23:34  resident 809 MiB (+108 MiB), virtual 833 MiB
2026-07-10T23:29:34  resident 916 MiB (+107 MiB), virtual 990 MiB
2026-07-10T23:39:34  resident 989 MiB (+73 MiB), virtual 1308 MiB
2026-07-10T23:49:34  resident 1008 MiB (+18 MiB), virtual 1507 MiB
2026-07-10T23:59:35  resident 914 MiB (-94 MiB), virtual 1554 MiB
2026-07-11T00:08:05  resident 1009 MiB (+95 MiB), virtual 1734 MiB
2026-07-11T00:15:05  resident 878 MiB (-131 MiB), virtual 1832 MiB
2026-07-11T00:20:05  resident 986 MiB (+108 MiB), virtual 1916 MiB
2026-07-11T00:30:05  resident 968 MiB (-18 MiB), virtual 2066 MiB
2026-07-11T00:40:06  resident 955 MiB (-12 MiB), virtual 2072 MiB
2026-07-11T00:45:06  resident 1051 MiB (+95 MiB), virtual 2215 MiB
2026-07-11T00:54:06  resident 1157 MiB (+105 MiB), virtual 2385 MiB
2026-07-11T01:04:06  resident 1102 MiB (-54 MiB), virtual 2493 MiB
2026-07-11T01:14:07  resident 1126 MiB (+23 MiB), virtual 2546 MiB
2026-07-11T01:24:07  resident 1208 MiB (+81 MiB), virtual 2736 MiB
2026-07-11T01:34:07  resident 1261 MiB (+53 MiB), virtual 2844 MiB
2026-07-11T01:44:07  resident 1223 MiB (-37 MiB), virtual 2876 MiB
2026-07-11T01:54:08  resident 1218 MiB (-5 MiB), virtual 2875 MiB
2026-07-11T02:04:08  resident 1218 MiB (+0 MiB), virtual 2876 MiB
2026-07-11T02:14:08  resident 1217 MiB (-1 MiB), virtual 2874 MiB
2026-07-11T02:24:09  resident 1217 MiB (+0 MiB), virtual 2875 MiB
2026-07-11T02:34:09  resident 1218 MiB (+0 MiB), virtual 2874 MiB
2026-07-11T02:44:09  resident 1218 MiB (+0 MiB), virtual 2874 MiB
2026-07-11T02:54:09  resident 1217 MiB (+0 MiB), virtual 2874 MiB
2026-07-11T03:04:10  resident 1218 MiB (+0 MiB), virtual 2875 MiB
2026-07-11T03:14:10  resident 1217 MiB (-1 MiB), virtual 2873 MiB
2026-07-11T03:24:10  resident 1216 MiB (+0 MiB), virtual 2873 MiB
2026-07-11T03:34:10  resident 1216 MiB (+0 MiB), virtual 2873 MiB
2026-07-11T03:44:11  resident 1218 MiB (+1 MiB), virtual 2874 MiB
2026-07-11T03:54:11  resident 1217 MiB (+0 MiB), virtual 2874 MiB
2026-07-11T04:04:11  resident 1217 MiB (+0 MiB), virtual 2873 MiB
2026-07-11T04:14:11  resident 1218 MiB (+1 MiB), virtual 2874 MiB
2026-07-11T04:24:12  resident 1216 MiB (-1 MiB), virtual 2873 MiB
2026-07-11T04:34:12  resident 1218 MiB (+1 MiB), virtual 2874 MiB
2026-07-11T04:44:12  resident 1166 MiB (-51 MiB), virtual 2874 MiB
2026-07-11T04:54:13  resident 1144 MiB (-22 MiB), virtual 2874 MiB
2026-07-11T05:04:13  resident 1143 MiB (+0 MiB), virtual 2874 MiB
2026-07-11T05:14:13  resident 1141 MiB (-2 MiB), virtual 2871 MiB
2026-07-11T05:24:13  resident 1141 MiB (+0 MiB), virtual 2872 MiB
2026-07-11T05:34:14  resident 1141 MiB (+0 MiB), virtual 2871 MiB
2026-07-11T05:44:14  resident 1141 MiB (+0 MiB), virtual 2872 MiB
2026-07-11T05:54:14  resident 1141 MiB (+0 MiB), virtual 2872 MiB
2026-07-11T06:04:14  resident 1141 MiB (+0 MiB), virtual 2872 MiB
2026-07-11T06:14:15  resident 1141 MiB (+0 MiB), virtual 2871 MiB
2026-07-11T06:24:15  resident 1141 MiB (+0 MiB), virtual 2871 MiB
2026-07-11T06:34:15  resident 1141 MiB (+0 MiB), virtual 2872 MiB
2026-07-11T06:44:16  resident 1141 MiB (+0 MiB), virtual 2871 MiB
2026-07-11T06:54:16  resident 1141 MiB (+0 MiB), virtual 2872 MiB
2026-07-11T07:04:16  resident 1145 MiB (+3 MiB), virtual 2871 MiB
2026-07-11T07:14:16  resident 1145 MiB (+0 MiB), virtual 2871 MiB
2026-07-11T07:24:17  resident 1183 MiB (+37 MiB), virtual 2908 MiB
2026-07-11T07:30:47  resident 1004 MiB (-178 MiB), virtual 2908 MiB
2026-07-11T07:38:47  resident 1108 MiB (+104 MiB), virtual 3000 MiB
2026-07-11T07:44:17  resident 1225 MiB (+116 MiB), virtual 3076 MiB
2026-07-11T07:46:47  resident 1351 MiB (+126 MiB), virtual 3077 MiB
2026-07-11T07:50:17  resident 1501 MiB (+149 MiB), virtual 3247 MiB
```

</details>

<details>
<summary>Zed.log.old — 464 records (08.07 00:11 — 10.07 07:59)</summary>

```
2026-07-08T00:11:29  resident 52 MiB,             virtual 24 MiB     ← RESTART
2026-07-08T00:11:59  resident 653 MiB (+600 MiB), virtual 654 MiB
2026-07-08T00:14:29  resident 733 MiB (+80 MiB), virtual 746 MiB
2026-07-08T00:24:29  resident 744 MiB (+11 MiB), virtual 756 MiB
2026-07-08T00:34:29  resident 736 MiB (-8 MiB), virtual 758 MiB
2026-07-08T00:37:29  resident 834 MiB (+97 MiB), virtual 893 MiB
2026-07-08T00:47:29  resident 909 MiB (+75 MiB), virtual 876 MiB
2026-07-08T00:48:29  resident 621 MiB (-288 MiB), virtual 871 MiB
2026-07-08T00:55:00  resident 723 MiB (+102 MiB), virtual 1058 MiB
2026-07-08T01:01:00  resident 800 MiB (+77 MiB), virtual 1098 MiB
2026-07-08T01:02:30  resident 1019 MiB (+219 MiB), virtual 1457 MiB
2026-07-08T01:03:00  resident 783 MiB (-236 MiB), virtual 1112 MiB
2026-07-08T01:13:00  resident 834 MiB (+51 MiB), virtual 1176 MiB
2026-07-08T01:16:30  resident 1156 MiB (+321 MiB), virtual 1815 MiB
2026-07-08T01:17:00  resident 1640 MiB (+484 MiB), virtual 2548 MiB
2026-07-08T01:17:30  resident 751 MiB (-889 MiB), virtual 1218 MiB
2026-07-08T01:20:00  resident 1143 MiB (+392 MiB), virtual 1796 MiB
2026-07-08T01:20:30  resident 773 MiB (-369 MiB), virtual 1262 MiB
2026-07-08T01:22:30  resident 930 MiB (+156 MiB), virtual 1432 MiB
2026-07-08T01:23:30  resident 830 MiB (-100 MiB), virtual 1375 MiB
2026-07-08T01:33:31  resident 751 MiB (-78 MiB), virtual 1434 MiB
2026-07-08T01:36:01  resident 842 MiB (+90 MiB), virtual 1536 MiB
2026-07-08T01:38:31  resident 718 MiB (-123 MiB), virtual 1460 MiB
2026-07-08T01:43:01  resident 857 MiB (+139 MiB), virtual 1626 MiB
2026-07-08T01:43:31  resident 739 MiB (-117 MiB), virtual 1468 MiB
2026-07-08T01:53:31  resident 711 MiB (-28 MiB), virtual 1469 MiB
2026-07-08T02:03:31  resident 710 MiB (+0 MiB), virtual 1469 MiB
2026-07-08T02:13:32  resident 710 MiB (+0 MiB), virtual 1470 MiB
2026-07-08T02:23:32  resident 712 MiB (+1 MiB), virtual 1469 MiB
2026-07-08T02:33:32  resident 712 MiB (+0 MiB), virtual 1469 MiB
2026-07-08T06:37:52  resident 66 MiB,             virtual 24 MiB     ← RESTART (after app_will_quit)
2026-07-08T06:38:22  resident 921 MiB (+855 MiB), virtual 928 MiB
2026-07-08T06:43:22  resident 64 MiB (-856 MiB), virtual 963 MiB
2026-07-08T06:44:52  resident 140 MiB (+76 MiB), virtual 964 MiB
2026-07-08T06:47:22  resident 221 MiB (+80 MiB), virtual 1026 MiB
2026-07-08T06:48:22  resident 1906 MiB (+1685 MiB), virtual 3442 MiB   ← >3 GB virtual
2026-07-08T06:48:52  resident 278 MiB (-1627 MiB), virtual 1067 MiB
2026-07-08T06:58:52  resident 287 MiB (+8 MiB), virtual 1076 MiB
2026-07-08T07:08:53  resident 288 MiB (+0 MiB), virtual 1076 MiB
2026-07-08T07:18:53  resident 289 MiB (+0 MiB), virtual 1075 MiB
2026-07-08T07:28:53  resident 288 MiB (+0 MiB), virtual 1074 MiB
2026-07-08T07:38:53  resident 288 MiB (+0 MiB), virtual 1075 MiB
2026-07-08T07:48:54  resident 288 MiB (+0 MiB), virtual 1075 MiB
2026-07-08T07:58:54  resident 289 MiB (+0 MiB), virtual 1075 MiB
2026-07-08T08:08:54  resident 288 MiB (+0 MiB), virtual 1074 MiB
...
2026-07-08T18:43:55  resident 186 MiB (+0 MiB), virtual 1072 MiB   (stable ~288 MiB all day)
2026-07-08T18:44:55  resident 311 MiB (+124 MiB), virtual 1075 MiB
2026-07-08T18:49:25  resident 150 MiB (-160 MiB), virtual 1129 MiB
2026-07-08T18:51:55  resident 226 MiB (+75 MiB), virtual 1168 MiB
2026-07-08T18:57:25  resident 393 MiB (+166 MiB), virtual 1348 MiB
2026-07-08T18:57:55  resident 270 MiB (-122 MiB), virtual 1173 MiB
2026-07-08T19:00:55  resident 1005 MiB (+734 MiB), virtual 2181 MiB
2026-07-08T19:01:25  resident 312 MiB (-692 MiB), virtual 1209 MiB
2026-07-08T19:02:25  resident 1545 MiB (+1233 MiB), virtual 2922 MiB
2026-07-08T19:02:55  resident 2611 MiB (+1065 MiB), virtual 4394 MiB   ← >2 GB
2026-07-08T19:03:25  resident 355 MiB (-2255 MiB), virtual 1250 MiB
2026-07-08T19:05:55  resident 1414 MiB (+1058 MiB), virtual 2704 MiB
2026-07-08T19:06:25  resident 366 MiB (-1048 MiB), virtual 1258 MiB
2026-07-08T19:08:55  resident 562 MiB (+196 MiB), virtual 1529 MiB
2026-07-08T19:09:25  resident 2023 MiB (+1460 MiB), virtual 3536 MiB   ← >2 GB
2026-07-08T19:09:55  resident 943 MiB (-1080 MiB), virtual 2034 MiB
2026-07-08T19:10:25  resident 415 MiB (-528 MiB), virtual 1309 MiB
2026-07-08T19:10:55  resident 2072 MiB (+1657 MiB), virtual 3592 MiB   ← >2 GB
2026-07-08T19:11:25  resident 416 MiB (-1656 MiB), virtual 1322 MiB
2026-07-08T19:14:26  resident 1410 MiB (+993 MiB), virtual 2681 MiB
2026-07-08T19:14:56  resident 437 MiB (-972 MiB), virtual 1340 MiB
2026-07-08T19:15:26  resident 797 MiB (+359 MiB), virtual 1820 MiB
2026-07-08T19:15:56  resident 462 MiB (-335 MiB), virtual 1362 MiB
2026-07-08T19:16:26  resident 1578 MiB (+1116 MiB), virtual 2864 MiB
2026-07-08T19:16:56  resident 464 MiB (-1114 MiB), virtual 1364 MiB
2026-07-08T19:21:26  resident 919 MiB (+455 MiB), virtual 1989 MiB
2026-07-08T19:21:56  resident 500 MiB (-418 MiB), virtual 1389 MiB
2026-07-08T19:22:26  resident 1583 MiB (+1083 MiB), virtual 2834 MiB
2026-07-08T19:22:56  resident 516 MiB (-1067 MiB), virtual 1405 MiB
2026-07-08T19:24:26  resident 3141 MiB (+2624 MiB), virtual 4923 MiB   ← >3 GB
2026-07-08T19:24:56  resident 527 MiB (-2614 MiB), virtual 1417 MiB
2026-07-08T19:25:56  resident 860 MiB (+332 MiB), virtual 1852 MiB
2026-07-08T19:26:26  resident 564 MiB (-296 MiB), virtual 1457 MiB
2026-07-08T19:26:56  resident 1571 MiB (+1007 MiB), virtual 2795 MiB
2026-07-08T19:27:26  resident 969 MiB (-602 MiB), virtual 2008 MiB
2026-07-08T19:27:56  resident 1370 MiB (+401 MiB), virtual 2530 MiB
2026-07-08T19:28:26  resident 2679 MiB (+1308 MiB), virtual 4271 MiB   ← >2 GB
2026-07-08T19:28:56  resident 3044 MiB (+365 MiB), virtual 4748 MiB   ← >3 GB
2026-07-08T19:29:26  resident 603 MiB (-2441 MiB), virtual 1498 MiB
2026-07-08T19:29:56  resident 1899 MiB (+1295 MiB), virtual 3215 MiB   ← >3 GB virtual
2026-07-08T19:30:26  resident 608 MiB (-1291 MiB), virtual 1505 MiB
2026-07-08T19:30:56  resident 1553 MiB (+945 MiB), virtual 2798 MiB
2026-07-08T19:31:26  resident 619 MiB (-934 MiB), virtual 1539 MiB
2026-07-08T19:36:56  resident 685 MiB (+66 MiB), virtual 1532 MiB
2026-07-08T19:43:27  resident 815 MiB (+130 MiB), virtual 1740 MiB
...
2026-07-08T19:55:27  resident 1770 MiB (+1089 MiB), virtual 2996 MiB
2026-07-08T19:55:57  resident 700 MiB (-1070 MiB), virtual 1585 MiB
2026-07-08T19:56:27  resident 1099 MiB (+398 MiB), virtual 2099 MiB
2026-07-08T19:56:57  resident 3029 MiB (+1930 MiB), virtual 4601 MiB   ← >3 GB
2026-07-08T19:57:27  resident 2680 MiB (-349 MiB), virtual 4145 MiB
2026-07-08T19:58:27  resident 1426 MiB (-1254 MiB), virtual 2914 MiB
2026-07-08T19:58:57  resident 891 MiB (-535 MiB), virtual 2218 MiB
2026-07-08T19:59:27  resident 1011 MiB (+120 MiB), virtual 2401 MiB
2026-07-08T19:59:57  resident 1649 MiB (+637 MiB), virtual 3185 MiB   ← >3 GB virtual
2026-07-08T20:00:27  resident 703 MiB (-945 MiB), virtual 1969 MiB
2026-07-08T20:00:57  resident 587 MiB (-115 MiB), virtual 1809 MiB
2026-07-08T20:01:27  resident 2950 MiB (+2362 MiB), virtual 4765 MiB
2026-07-08T20:01:57  resident 616 MiB (-2333 MiB), virtual 1860 MiB
2026-07-08T20:11:57  resident 683 MiB (+66 MiB), virtual 1823 MiB
2026-07-08T20:13:57  resident 611 MiB (-71 MiB), virtual 1825 MiB
2026-07-08T20:16:57  resident 1783 MiB (+1171 MiB), virtual 3296 MiB   ← >3 GB virtual
2026-07-08T20:17:27  resident 644 MiB (-1138 MiB), virtual 1861 MiB
2026-07-08T20:17:57  resident 2278 MiB (+1634 MiB), virtual 3904 MiB   ← >2 GB
2026-07-08T20:18:27  resident 1024 MiB (-1254 MiB), virtual 2321 MiB
2026-07-08T20:18:57  resident 1983 MiB (+959 MiB), virtual 3534 MiB   ← >3 GB virtual
2026-07-08T20:19:57  resident 727 MiB (-1256 MiB), virtual 1978 MiB
...
2026-07-08T21:24:59  resident 5571 MiB (+4431 MiB), virtual 8155 MiB   ← >3 GB
2026-07-08T21:25:29  resident 706 MiB (-4865 MiB), virtual 2510 MiB
...
2026-07-08T21:37:29  resident 3512 MiB (+2706 MiB), virtual 5637 MiB   ← >3 GB
...
2026-07-08T21:46:30  resident 2451 MiB (+1624 MiB), virtual 4420 MiB
...
2026-07-08T21:50:30  resident 2062 MiB (+1187 MiB), virtual 3987 MiB
2026-07-08T21:51:00  resident 888 MiB (-1174 MiB), virtual 2645 MiB
2026-07-08T21:52:30  resident 5621 MiB (+4732 MiB), virtual 7971 MiB   ← >3 GB
2026-07-08T21:53:00  resident 4690 MiB (-930 MiB), virtual 7674 MiB   ← >3 GB
2026-07-08T21:53:30  resident 308 MiB (-4382 MiB), virtual 2715 MiB
...
2026-07-08T22:03:30  resident 1822 MiB (+1438 MiB), virtual 4328 MiB
2026-07-08T22:04:00  resident 397 MiB (-1425 MiB), virtual 2734 MiB
2026-07-08T22:06:30  resident 3138 MiB (+2741 MiB), virtual 5796 MiB   ← >3 GB
2026-07-08T22:07:00  resident 398 MiB (-2740 MiB), virtual 2733 MiB
...
2026-07-08T22:41:31  resident 2446 MiB (+1162 MiB), virtual 4940 MiB
...
2026-07-08T22:48:01  resident 4660 MiB (+3900 MiB), virtual 7353 MiB   ← >3 GB
...
2026-07-08T22:55:01  resident 1284 MiB (+620 MiB), virtual 3657 MiB
...
2026-07-08T23:04:32  resident 3010 MiB (+2437 MiB), virtual 5734 MiB   ← >3 GB
...
2026-07-08T23:24:02  resident 6658 MiB (+6122 MiB), virtual 9655 MiB   ← >3 GB
2026-07-08T23:24:32  resident 1312 MiB (-5346 MiB), virtual 3952 MiB
...
2026-07-08T23:56:33  resident 6173 MiB (+5620 MiB), virtual 9081 MiB   ← >3 GB
2026-07-08T23:57:03  resident 610 MiB (-5562 MiB), virtual 3272 MiB
...
2026-07-08T23:59:33  resident 2351 MiB (+1758 MiB), virtual 5103 MiB   ← >3 GB virtual
...
2026-07-09T00:11:33  resident 1235 MiB (+402 MiB), virtual 3903 MiB
...
2026-07-09T06:01:13  resident 1365 MiB (+635 MiB), virtual 4165 MiB   ← >3 GB virtual
...
2026-07-09T06:14:43  resident 3026 MiB (+2121 MiB), virtual 5876 MiB   ← >3 GB
2026-07-09T06:15:13  resident 853 MiB (-2172 MiB), virtual 3579 MiB
2026-07-09T06:15:43  resident 2725 MiB (+1872 MiB), virtual 5547 MiB
2026-07-09T06:16:13  resident 854 MiB (-1870 MiB), virtual 3580 MiB
2026-07-09T06:18:43  resident 5238 MiB (+4384 MiB), virtual 8111 MiB   ← >3 GB
2026-07-09T06:19:13  resident 7707 MiB (+2468 MiB), virtual 10731 MiB   ← >3 GB
2026-07-09T06:19:43  resident 2642 MiB (-5064 MiB), virtual 5438 MiB
2026-07-09T06:20:13  resident 851 MiB (-1791 MiB), virtual 3603 MiB
2026-07-09T06:20:43  resident 1193 MiB (+341 MiB), virtual 3953 MiB
2026-07-09T06:21:13  resident 899 MiB (-293 MiB), virtual 3649 MiB
2026-07-09T06:21:43  resident 1172 MiB (+272 MiB), virtual 3943 MiB
2026-07-09T06:22:13  resident 873 MiB (-299 MiB), virtual 3651 MiB
2026-07-09T06:22:43  resident 10090 MiB (+9217 MiB), virtual 13456 MiB   ← >3 GB ★ ABSOLUTE PEAK
2026-07-09T06:23:13  resident 3545 MiB (-6545 MiB), virtual 16003 MiB   ← >3 GB ★ VIRTUAL PEAK
2026-07-09T06:23:43  resident 5462 MiB (+1917 MiB), virtual 11344 MiB   ← >3 GB
2026-07-09T06:24:13  resident 1029 MiB (-4433 MiB), virtual 4392 MiB
...
2026-07-09T06:28:14  resident 5215 MiB (+4744 MiB), virtual 8583 MiB   ← >3 GB
...
2026-07-09T06:29:14  resident 1942 MiB (+1471 MiB), virtual 5262 MiB
...
2026-07-09T19:12:57  resident 69 MiB,             virtual 24 MiB     ← RESTART
...
2026-07-09T22:12:02  resident 1367 MiB (+157 MiB), virtual 3140 MiB   ← >3 GB virtual
2026-07-09T22:12:13  resident 53 MiB,             virtual 24 MiB     ← RESTART
...
2026-07-09T22:22:13  resident 50 MiB,             virtual 24 MiB     ← RESTART
...
2026-07-09T22:30:30  resident 53 MiB,             virtual 24 MiB     ← RESTART
...
2026-07-10T07:44:05  resident 51 MiB,             virtual 24 MiB     ← RESTART
...
2026-07-10T07:50:07  resident 56 MiB,             virtual 24 MiB     ← RESTART
...
2026-07-10T07:59:14  resident 53 MiB,             virtual 24 MiB     ← RESTART
```

</details>

---

## Memory Peaks (>3 GB Resident)

### From `Zed.log` (14 peaks)

| # | Date | Time | Resident | Virtual | Delta |
|---|---|---|---|---|---|
| 1 | 10.07 | 08:18:50 | **3 090 MiB** | 3 990 MiB | +1 575 MiB |
| 2 | 10.07 | 08:19:21 | **4 344 MiB** | 5 649 MiB | +1 253 MiB |
| 3 | 10.07 | 17:17:24 | **3 745 MiB** | 7 074 MiB | +2 249 MiB |
| 4 | 10.07 | 18:25:47 | **4 345 MiB** | 6 551 MiB | +3 322 MiB |
| 5 | 10.07 | 18:27:48 | **3 139 MiB** | 4 721 MiB | +2 050 MiB |
| 6 | 10.07 | 18:30:48 | **5 100 MiB** | 7 746 MiB | +3 533 MiB |
| 7 | 10.07 | 18:31:18 | **7 406 MiB** | 11 299 MiB | +2 306 MiB |
| 8 | 10.07 | 18:32:48 | **4 619 MiB** | 7 015 MiB | +3 625 MiB |
| 9 | 10.07 | 18:33:18 | **7 561 MiB** | 11 406 MiB | +2 941 MiB |
| 10 | 10.07 | 18:46:18 | **3 091 MiB** | 4 664 MiB | +1 681 MiB |
| 11 | 10.07 | 19:02:48 | **3 730 MiB** | 5 626 MiB | +2 581 MiB |
| 12 | 10.07 | 19:35:49 | **3 265 MiB** | 5 451 MiB | +1 215 MiB |

### From `Zed.log.old` (23 peaks, only >3 GB)

| # | Date | Time | Resident | Virtual | Delta |
|---|---|---|---|---|---|
| 1 | 08.07 | 19:24:26 | **3 141 MiB** | 4 923 MiB | +2 624 MiB |
| 2 | 08.07 | 19:28:56 | **3 044 MiB** | 4 748 MiB | +365 MiB |
| 3 | 08.07 | 19:56:57 | **3 029 MiB** | 4 601 MiB | +1 930 MiB |
| 4 | 08.07 | 20:01:27 | **3 950 MiB** | 4 765 MiB | +2 362 MiB |
| 5 | 08.07 | 20:17:57 | **2 278 MiB** | 3 904 MiB | +1 634 MiB |
| 6 | 08.07 | 21:24:59 | **5 571 MiB** | 8 155 MiB | +4 431 MiB |
| 7 | 08.07 | 21:37:29 | **3 512 MiB** | 5 637 MiB | +2 706 MiB |
| 8 | 08.07 | 21:52:30 | **5 621 MiB** | 7 971 MiB | +4 732 MiB |
| 9 | 08.07 | 21:53:00 | **4 690 MiB** | 7 674 MiB | -930 MiB |
| 10 | 08.07 | 22:06:30 | **3 138 MiB** | 5 796 MiB | +2 741 MiB |
| 11 | 08.07 | 22:30:01 | **2 397 MiB** | 4 962 MiB | +1 981 MiB |
| 12 | 08.07 | 22:41:31 | **2 446 MiB** | 4 940 MiB | +1 162 MiB |
| 13 | 08.07 | 22:48:01 | **4 660 MiB** | 7 353 MiB | +3 900 MiB |
| 14 | 08.07 | 23:04:32 | **3 010 MiB** | 5 734 MiB | +2 437 MiB |
| 15 | 08.07 | 23:24:02 | **6 658 MiB** | 9 655 MiB | +6 122 MiB |
| 16 | 08.07 | 23:56:33 | **6 173 MiB** | 9 081 MiB | +5 620 MiB |
| 17 | 09.07 | 06:14:43 | **3 026 MiB** | 5 876 MiB | +2 121 MiB |
| 18 | 09.07 | 06:18:43 | **5 238 MiB** | 8 111 MiB | +4 384 MiB |
| 19 | 09.07 | 06:19:13 | **7 707 MiB** | 10 731 MiB | +2 468 MiB |
| 20 | 09.07 | **06:22:43** | **10 090 MiB** 🔥 | **13 456 MiB** | **+9 217 MiB** |
| 21 | 09.07 | 06:23:13 | 3 545 MiB | **16 003 MiB** 🔥 | -6 545 MiB |
| 22 | 09.07 | 06:23:43 | **5 462 MiB** | 11 344 MiB | +1 917 MiB |
| 23 | 09.07 | 06:28:14 | **5 215 MiB** | 8 583 MiB | +4 744 MiB |

---

## Crash Pattern

### Typical Crash Cycle

```
1. Resident memory grows by 500-3000 MiB in 30 seconds (usually during agent/LLM activity)
2. Virtual memory far exceeds physical limits (up to 16 GB virtual with 15.4 GB RAM)
3. Mass `window not found` errors appear
4. On tab/window close — `app_will_quit timeout` (30 sec timeout)
5. Zed crashes or is killed by the OS (OOM killer)
6. Automatic restart within 2-3 seconds
7. Memory resets to ~50 MiB resident
```

### Worst Episode: 09.07 06:18-06:29

```mermaid
timeline
    title 09.07.2026 06:18 — 06:29 — OOM Meltdown
    06:18:43 : Resident 5,238 MiB, Virtual 8,111 MiB
    06:19:13 : Resident 7,707 MiB, Virtual 10,731 MiB
    06:22:43 : Resident 10,090 MiB, Virtual 13,456 MiB (ABSOLUTE PEAK)
    06:23:13 : Resident 3,545 MiB, Virtual 16,003 MiB (VIRTUAL PEAK)
    06:23:43 : Resident 5,462 MiB, Virtual 11,344 MiB
    06:28:14 : Resident 5,215 MiB, Virtual 8,583 MiB
    06:42:50 : app_will_quit timeout → RESTART
```

### Worst Episode in Zed.log: 10.07 18:25-18:33

```mermaid
timeline
    title 10.07.2026 18:25 — 18:33 — Peak Cascade
    18:25:47 : Resident 4,345 MiB, Virtual 6,551 MiB
    18:27:48 : Resident 3,139 MiB, Virtual 4,721 MiB
    18:30:48 : Resident 5,100 MiB, Virtual 7,746 MiB
    18:31:18 : Resident 7,406 MiB, Virtual 11,299 MiB
    18:32:48 : Resident 4,619 MiB, Virtual 7,015 MiB
    18:33:18 : Resident 7,561 MiB, Virtual 11,406 MiB
```

### Peak Frequency (>3GB)

- **08.07 evening (19:00-23:00):** 16 peaks in 4 hours — agent session caused a cascade of leaks
- **09.07 morning (06:00-06:30):** 6 peaks, including the absolute record of 10 GB — overnight session with agent_ui
- **09.07 night (22:00-22:30):** 3 quick restarts in a row — crash loop
- **10.07 morning (08:00-09:30):** 2 peaks, then 3 restarts in 2 minutes — crash-restart cycle
- **10.07 evening (18:00-19:00):** 8 peaks in one hour — densest cluster

---

## Related Zed Bugs

| Bug | Description | Status |
|---|---|---|
| [#60475](https://github.com/zed-industries/zed/issues/60475) | Stack buffer overrun in gpui → crash on window close | Fixed by driver |
| [#59442](https://github.com/zed-industries/zed/issues/59442) | agent_ui SQLite write loop → memory leak | Active |
| [#57126](https://github.com/zed-industries/zed/issues/57126) | agent memory usage grows without bound | Active |
| [#56347](https://github.com/zed-industries/zed/issues/56347) | LSP Edit tabs → OOM with many open tabs | Active |

### Observed Symptoms in Logs

1. **agent_loop leak** — peaks coincide with `agent::thread::Thread::send` and `Received prompt request` in logs, indicating a leak in agent UI (#59442, #57126)
2. **gpui windows not closing** — `window not found` (line 1604) appears dozens of times before each `app_will_quit timeout`. Indicates a race condition in gpui when closing windows (#60475)
3. **Virtual Memory >> Physical RAM** — virtual reaches 16 GB with 15.4 GB physical memory. This leads to swapping and OOM-killer
4. **Cascade restarts** — after the first crash the system enters a loop: start → rapid memory growth → crash → start. Typical of a leak that doesn't reset on restart

---

## Recommendations

1. **Bug report:** combine logs with the pattern `agent` → `window not found` → `app_will_quit timeout`
2. **Temporary fix:** limit Zed memory via `--max-memory` or drop agent after session
3. **Monitoring:** add `zed --memory-report` for early leak detection
4. **Workaround:** when `window not found` appears in the log — close extra agent tabs

---

*Generated from `Zed.log` (5018 lines) and `Zed.log.old` (3911 lines)*
