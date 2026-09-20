# City Map

@river: 梅湾村 River | path=0.05,0.24;0.18,0.30;0.38,0.27;0.56,0.33;0.78,0.28;0.95,0.35 | width=0.08
@node: Lake Block | kind=hub | district=Lake Block | category=residential | x=2.5 | y=3.2
@node: Hill Block | kind=hub | district=Hill Block | category=residential | x=5.6 | y=3.2
@node: East Block | kind=hub | district=East Block | category=residential | x=8.7 | y=3.2
@node: Tech Park | kind=hub | district=Tech Park | category=commerce | x=2.5 | y=5.8
@node: Industrial Park | kind=hub | district=Industrial Park | category=industry | x=5.6 | y=5.8
@node: Financial District | kind=hub | district=Financial District | category=commerce | x=8.7 | y=5.8
@road: Lake Block -> Hill Block | type=arterial
@road: Hill Block -> East Block | type=arterial
@road: East Block -> Tech Park | type=arterial
@road: Tech Park -> Industrial Park | type=arterial
@road: Industrial Park -> Financial District | type=arterial
@road: Financial District -> Lake Block | type=collector

- City: 梅湾村
  - Hub: Lake Block
    - Nearby: Building L-01
      - Floor: 1F
        - Flat: 1A
        - Flat: 1B
      - Floor: 2F
        - Flat: 2A
        - Flat: 2B
      - Floor: 3F
        - Flat: 3A
        - Flat: 3B
      - Floor: 4F
        - Flat: 4A
        - Flat: 4B
    - Nearby: Building L-02
      - Floor: 1F
        - Flat: 1A
        - Flat: 1B
      - Floor: 2F
        - Flat: 2A
        - Flat: 2B
    - Nearby: Building L-03
      - Floor: 1F
        - Flat: 1A
        - Flat: 1B
      - Floor: 2F
        - Flat: 2A
        - Flat: 2B
      - Floor: 3F
        - Flat: 3A
        - Flat: 3B
      - Floor: 4F
        - Flat: 4A
        - Flat: 4B
    - Nearby: Neighborhood Clinic
    - Nearby: Pocket Park
  - Hub: Hill Block
    - Nearby: Building H-01
      - Floor: 1F
        - Flat: 1A
        - Flat: 1B
      - Floor: 2F
        - Flat: 2A
        - Flat: 2B
      - Floor: 3F
        - Flat: 3A
        - Flat: 3B
      - Floor: 4F
        - Flat: 4A
        - Flat: 4B
    - Nearby: Building H-02
      - Floor: 1F
        - Flat: 1A
        - Flat: 1B
      - Floor: 2F
        - Flat: 2A
        - Flat: 2B
    - Nearby: Building H-03
      - Floor: 1F
        - Flat: 1A
        - Flat: 1B
        - Flat: 1C
      - Floor: 2F
        - Flat: 2A
        - Flat: 2B
        - Flat: 2C
    - Nearby: Neighborhood Clinic
    - Nearby: Pocket Park
  - Hub: East Block
    - Nearby: Building E-01
      - Floor: 1F
        - Flat: 1A
        - Flat: 1B
        - Flat: 1C
      - Floor: 2F
        - Flat: 2A
        - Flat: 2B
        - Flat: 2C
      - Floor: 3F
        - Flat: 3A
        - Flat: 3B
        - Flat: 3C
      - Floor: 4F
        - Flat: 4A
        - Flat: 4B
        - Flat: 4C
    - Nearby: Building E-02
      - Floor: 1F
        - Flat: 1A
        - Flat: 1B
        - Flat: 1C
      - Floor: 2F
        - Flat: 2A
        - Flat: 2B
        - Flat: 2C
    - Nearby: Neighborhood Clinic
    - Nearby: Pocket Park
  - Hub: Tech Park
    - Nearby: R&D Center
    - Nearby: Innovation Hub
    - Nearby: Admin Office
    - Nearby: Startup Incubator
  - Hub: Industrial Park
    - Nearby: Manufacturing Zone A
    - Nearby: Manufacturing Zone B
    - Nearby: Logistics Yard
    - Nearby: Power Substation
    - Nearby: Freight Depot
  - Hub: Financial District
    - Nearby: Finance Plaza
    - Nearby: Riverside Tower
    - Nearby: Insurance Center
    - Nearby: Business Hotel
