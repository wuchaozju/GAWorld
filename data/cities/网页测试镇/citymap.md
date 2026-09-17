# City Map

@river: 网页测试镇 River | path=0.05,0.24;0.18,0.30;0.38,0.27;0.56,0.33;0.78,0.28;0.95,0.35 | width=0.08
@node: West Block | kind=hub | district=West Block | category=residential | x=2.5 | y=3.2
@node: Lake Block | kind=hub | district=Lake Block | category=residential | x=5.6 | y=3.2
@node: Central Block | kind=hub | district=Central Block | category=residential | x=8.7 | y=3.2
@node: Hill Block | kind=hub | district=Hill Block | category=residential | x=11.8 | y=3.2
@node: Riverside Park | kind=hub | district=Riverside Park | category=leisure | x=2.5 | y=5.8
@node: Industrial Park | kind=hub | district=Industrial Park | category=industry | x=5.6 | y=5.8
@node: Logistics Hub | kind=hub | district=Logistics Hub | category=industry | x=8.7 | y=5.8
@node: Stadium | kind=hub | district=Stadium | category=leisure | x=11.8 | y=5.8
@node: Tech Park | kind=hub | district=Tech Park | category=commerce | x=2.5 | y=8.4
@road: West Block -> Lake Block | type=arterial
@road: Lake Block -> Central Block | type=arterial
@road: Central Block -> Hill Block | type=arterial
@road: Hill Block -> Riverside Park | type=arterial
@road: Riverside Park -> Industrial Park | type=arterial
@road: Industrial Park -> Logistics Hub | type=arterial
@road: Logistics Hub -> Stadium | type=arterial
@road: Stadium -> Tech Park | type=arterial
@road: Tech Park -> West Block | type=collector

- City: 网页测试镇
  - Hub: West Block
    - Nearby: Building W-01
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
    - Nearby: Building W-02
      - Floor: 1F
        - Flat: 1A
        - Flat: 1B
      - Floor: 2F
        - Flat: 2A
        - Flat: 2B
      - Floor: 3F
        - Flat: 3A
        - Flat: 3B
    - Nearby: Neighborhood Clinic
    - Nearby: Pocket Park
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
    - Nearby: Neighborhood Clinic
    - Nearby: Pocket Park
  - Hub: Central Block
    - Nearby: Building C-01
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
    - Nearby: Building C-02
      - Floor: 1F
        - Flat: 1A
        - Flat: 1B
      - Floor: 2F
        - Flat: 2A
        - Flat: 2B
      - Floor: 3F
        - Flat: 3A
        - Flat: 3B
    - Nearby: Neighborhood Clinic
    - Nearby: Pocket Park
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
      - Floor: 3F
        - Flat: 3A
        - Flat: 3B
        - Flat: 3C
      - Floor: 4F
        - Flat: 4A
        - Flat: 4B
        - Flat: 4C
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
      - Floor: 4F
        - Flat: 4A
        - Flat: 4B
        - Flat: 4C
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
  - Hub: Riverside Park
    - Nearby: Riverwalk
    - Nearby: Playground
    - Nearby: Fitness Area
    - Nearby: Picnic Lawn
  - Hub: Industrial Park
    - Nearby: Manufacturing Zone A
    - Nearby: Manufacturing Zone B
    - Nearby: Logistics Yard
    - Nearby: Power Substation
    - Nearby: Freight Depot
  - Hub: Logistics Hub
    - Nearby: Freight Station
    - Nearby: Cold Storage Facility
    - Nearby: Sorting Center
    - Nearby: Truck Stop
  - Hub: Stadium
    - Nearby: Stadium Plaza
    - Nearby: Aquatic Center
    - Nearby: Training Grounds
    - Nearby: Sports Clinic
  - Hub: Tech Park
    - Nearby: R&D Center
    - Nearby: Innovation Hub
    - Nearby: Admin Office
    - Nearby: Startup Incubator
