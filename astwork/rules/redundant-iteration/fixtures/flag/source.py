from datetime import datetime

array = [x for x in range(1,101)]
before = datetime.now()
for i in range(100):
    x = 10 * 5          # Redundant (Invariant computation)
    y = array[i] + 2    # Valid (Changes with 'i')
    for j in range(1,10):
        z = y + 5
    print("Looping...") # Redundant iteration output
after = datetime.now()
print(f"Execution: {after - before}")