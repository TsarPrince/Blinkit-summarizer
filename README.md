### Pre-requisites:

1. Go to https://blinkit.com/account/orders
2. Copy the order_history curl from Network tab

<img width="1512" height="904" alt="Screenshot 2026-04-19 at 11 59 02 PM" src="https://github.com/user-attachments/assets/ba554fcb-a93a-49ea-9722-be6c7849c4da" />

3. Replace curl.sh (the script extracts the required headers and cookies from this while preveting [TLS Fingerprinting](https://www.youtube.com/watch?v=ISr2ETG4E4M) (Blinkit blocks direct curls via Cloudflare)

### Usage: 
```
  order_history.py <start_date> <end_date>
  Dates in ddmmyyyy format (both inclusive)

Example:
  .venv/bin/python order_history.py 15012026 19042026
```

### Sample Output:
https://docs.google.com/spreadsheets/d/1_gh_yzyWvx904ldMPxTYT-rTmMc0dNzW9NQDTYY6enc/edit?usp=sharing
