# Logic Chain

* Mapping energy consumption to ghg emissions
* The battery gave up x joules (unplugged) --> x grams of CO2e (how do we get here?). I can test it on my rig and will have to use coefficient from tests that convert already.
* The battery gave up x joules (plugged in): This is a bigger concern but I can't test it on my rig. I'd need a desktop.
* Region is a variable that I'd have to ingest as part of any meaningful output. That is also private information and would have to get permission in order to include? Otherwise estimate?
* energy_now is a level (how much energy is left in the battery right now in microWatt hours) - power_now is a rate (how fast is energy currently leaving or entering the battery in mWatts). Let's start with energy_now
* Clearly separate harness cost from workload snippet
* Maths: My baseline is 3.8W, of idle draw my quantum is 10mWh, update period is ~9.5s
  * energy_now is updating every ~8-11 seconds and each tick as about 10000 microWatt hours
  * Formula is <value> x 10^-6Wh x 3600

  Conversion Math:
  step        = 10,000 µWh
            = 10,000 × 10⁻⁶ Wh
            = 0.01 Wh
            = 10 mWh

1 Wh        = 3600 J
0.01 Wh     = 0.01 × 3600 = 36 J

interval    ≈ 9.5 s

power       = 36 J / 9.5 s
            ≈ 3.8 W

* What makes the measurements not reproducible?
- Variance. interference. Noise. How do I calculate measurement as a constant?
- In idle state, I'm dissipating 3.8W per tick. 
My energy_full is:22790000
My max_rapl is: 262143328850
My system is TDP up at 25W