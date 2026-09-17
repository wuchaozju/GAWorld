# City Map

@river: 乌镇镇 River | path=0.05,0.24;0.18,0.30;0.38,0.27;0.56,0.33;0.78,0.28;0.95,0.35 | width=0.08
@node: Hill Block | kind=hub | district=Hill Block | category=residential | x=2.5 | y=3.2
@node: West Block | kind=hub | district=West Block | category=residential | x=5.6 | y=3.2
@node: Lake Block | kind=hub | district=Lake Block | category=residential | x=8.7 | y=3.2
@node: East Block | kind=hub | district=East Block | category=residential | x=11.8 | y=3.2
@node: Night Market | kind=hub | district=Night Market | category=commerce | x=2.5 | y=5.8
@node: Central Station | kind=hub | district=Central Station | category=transit | x=5.6 | y=5.8
@node: Industrial Park | kind=hub | district=Industrial Park | category=industry | x=8.7 | y=5.8
@node: Stadium | kind=hub | district=Stadium | category=leisure | x=11.8 | y=5.8
@node: Waterfront | kind=hub | district=Waterfront | category=leisure | x=2.5 | y=8.4
@road: Hill Block -> West Block | type=arterial
@road: West Block -> Lake Block | type=arterial
@road: Lake Block -> East Block | type=arterial
@road: East Block -> Night Market | type=arterial
@road: Night Market -> Central Station | type=arterial
@road: Central Station -> Industrial Park | type=arterial
@road: Industrial Park -> Stadium | type=arterial
@road: Stadium -> Waterfront | type=arterial
@road: Waterfront -> Hill Block | type=collector

- City: 乌镇镇
  - Hub: Hill Block
    - Nearby: Building H-01
      - Floor: 1F
        - Flat: 1A
        - Flat: 1B
        - Flat: 1C
      - Floor: 2F
        - Flat: 2A
        - Flat: 2B
        - Flat: 2C
    - Nearby: Building H-02
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
    - Nearby: Building H-03
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
  - Hub: West Block
    - Nearby: Building W-01
      - Floor: 1F
        - Flat: 1A
        - Flat: 1B
      - Floor: 2F
        - Flat: 2A
        - Flat: 2B
    - Nearby: Building W-02
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
  - Hub: Lake Block
    - Nearby: Building L-01
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
    - Nearby: Building L-02
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
    - Nearby: Building L-03
      - Floor: 1F
        - Flat: 1A
        - Flat: 1B
      - Floor: 2F
        - Flat: 2A
        - Flat: 2B
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
  - Hub: Night Market
    - Nearby: Food Street
    - Nearby: Open Air Bazaar
    - Nearby: Corner Mart
    - Nearby: Cinema Alley
  - Hub: Central Station
    - Nearby: High Speed Rail Terminal
    - Nearby: Metro Concourse
    - Nearby: Taxi Loop
    - Nearby: Intercity Bus Terminal
  - Hub: Industrial Park
    - Nearby: Manufacturing Zone A
    - Nearby: Manufacturing Zone B
    - Nearby: Logistics Yard
    - Nearby: Power Substation
    - Nearby: Freight Depot
  - Hub: Stadium
    - Nearby: Stadium Plaza
    - Nearby: Aquatic Center
    - Nearby: Training Grounds
    - Nearby: Sports Clinic
  - Hub: Waterfront
    - Nearby: Riverside Port
    - Nearby: Marina Pier
    - Nearby: Riverfront Promenade
    - Nearby: Boathouse
