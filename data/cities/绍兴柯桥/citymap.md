# City Map

@river: 柯桥区 River | path=0.05,0.24;0.18,0.30;0.38,0.27;0.56,0.33;0.78,0.28;0.95,0.35 | width=0.08
@node: Central Block | kind=hub | district=Central Block | category=residential | x=2.5 | y=3.2
@node: East Block | kind=hub | district=East Block | category=residential | x=5.6 | y=3.2
@node: South Block | kind=hub | district=South Block | category=residential | x=8.7 | y=3.2
@node: Lake Block | kind=hub | district=Lake Block | category=residential | x=11.8 | y=3.2
@node: West Block | kind=hub | district=West Block | category=residential | x=14.9 | y=3.2
@node: Hill Block | kind=hub | district=Hill Block | category=residential | x=2.5 | y=5.8
@node: Airport District | kind=hub | district=Airport District | category=transit | x=5.6 | y=5.8
@node: Greenbelt Corridor | kind=hub | district=Greenbelt Corridor | category=leisure | x=8.7 | y=5.8
@node: University District | kind=hub | district=University District | category=education | x=11.8 | y=5.8
@node: Tech Park | kind=hub | district=Tech Park | category=commerce | x=14.9 | y=5.8
@node: Logistics Hub | kind=hub | district=Logistics Hub | category=industry | x=2.5 | y=8.4
@node: Financial District | kind=hub | district=Financial District | category=commerce | x=5.6 | y=8.4
@node: Riverside Park | kind=hub | district=Riverside Park | category=leisure | x=8.7 | y=8.4
@node: Industrial Park | kind=hub | district=Industrial Park | category=industry | x=11.8 | y=8.4
@node: Night Market | kind=hub | district=Night Market | category=commerce | x=14.9 | y=8.4
@node: Waterfront | kind=hub | district=Waterfront | category=leisure | x=2.5 | y=11.0
@node: Stadium | kind=hub | district=Stadium | category=leisure | x=5.6 | y=11.0
@node: Central Station | kind=hub | district=Central Station | category=transit | x=8.7 | y=11.0
@road: Central Block -> East Block | type=arterial
@road: East Block -> South Block | type=arterial
@road: South Block -> Lake Block | type=arterial
@road: Lake Block -> West Block | type=arterial
@road: West Block -> Hill Block | type=arterial
@road: Hill Block -> Airport District | type=arterial
@road: Airport District -> Greenbelt Corridor | type=arterial
@road: Greenbelt Corridor -> University District | type=arterial
@road: University District -> Tech Park | type=arterial
@road: Tech Park -> Logistics Hub | type=arterial
@road: Logistics Hub -> Financial District | type=arterial
@road: Financial District -> Riverside Park | type=arterial
@road: Riverside Park -> Industrial Park | type=arterial
@road: Industrial Park -> Night Market | type=arterial
@road: Night Market -> Waterfront | type=arterial
@road: Waterfront -> Stadium | type=arterial
@road: Stadium -> Central Station | type=arterial
@road: Central Station -> Central Block | type=collector
@metro: M1 | color=#8f5bd8 | stops=Central Block>East Block>South Block>Lake Block>West Block>Hill Block

- City: 柯桥区
  - Hub: Central Block
    - Nearby: Building C-01
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
    - Nearby: Building C-02
      - Floor: 1F
        - Flat: 1A
        - Flat: 1B
        - Flat: 1C
      - Floor: 2F
        - Flat: 2A
        - Flat: 2B
        - Flat: 2C
    - Nearby: Building C-03
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
    - Nearby: Building E-02
      - Floor: 1F
        - Flat: 1A
        - Flat: 1B
      - Floor: 2F
        - Flat: 2A
        - Flat: 2B
    - Nearby: Neighborhood Clinic
    - Nearby: Pocket Park
  - Hub: South Block
    - Nearby: Building S-01
      - Floor: 1F
        - Flat: 1A
        - Flat: 1B
      - Floor: 2F
        - Flat: 2A
        - Flat: 2B
    - Nearby: Building S-02
      - Floor: 1F
        - Flat: 1A
        - Flat: 1B
      - Floor: 2F
        - Flat: 2A
        - Flat: 2B
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
    - Nearby: Building L-02
      - Floor: 1F
        - Flat: 1A
        - Flat: 1B
      - Floor: 2F
        - Flat: 2A
        - Flat: 2B
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
        - Flat: 1C
      - Floor: 2F
        - Flat: 2A
        - Flat: 2B
        - Flat: 2C
      - Floor: 3F
        - Flat: 3A
        - Flat: 3B
        - Flat: 3C
    - Nearby: Building W-03
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
        - Flat: 1C
      - Floor: 2F
        - Flat: 2A
        - Flat: 2B
        - Flat: 2C
      - Floor: 3F
        - Flat: 3A
        - Flat: 3B
        - Flat: 3C
    - Nearby: Neighborhood Clinic
    - Nearby: Pocket Park
  - Hub: Airport District
    - Nearby: International Airport
    - Nearby: Airport Cargo Terminal
    - Nearby: Airport Hotel
    - Nearby: Air Traffic Control
  - Hub: Greenbelt Corridor
    - Nearby: Eco Trail
    - Nearby: Wetland Reserve
    - Nearby: Botanical Garden
    - Nearby: Outdoor Amphitheater
  - Hub: University District
    - Nearby: Main Library
    - Nearby: Engineering Building
    - Nearby: Arts Building
    - Nearby: Dormitory A
    - Nearby: Dormitory B
    - Nearby: Student Canteen
  - Hub: Tech Park
    - Nearby: R&D Center
    - Nearby: Innovation Hub
    - Nearby: Admin Office
    - Nearby: Startup Incubator
  - Hub: Logistics Hub
    - Nearby: Freight Station
    - Nearby: Cold Storage Facility
    - Nearby: Sorting Center
    - Nearby: Truck Stop
  - Hub: Financial District
    - Nearby: Finance Plaza
    - Nearby: Riverside Tower
    - Nearby: Insurance Center
    - Nearby: Business Hotel
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
  - Hub: Night Market
    - Nearby: Food Street
    - Nearby: Open Air Bazaar
    - Nearby: Corner Mart
    - Nearby: Cinema Alley
  - Hub: Waterfront
    - Nearby: Riverside Port
    - Nearby: Marina Pier
    - Nearby: Riverfront Promenade
    - Nearby: Boathouse
  - Hub: Stadium
    - Nearby: Stadium Plaza
    - Nearby: Aquatic Center
    - Nearby: Training Grounds
    - Nearby: Sports Clinic
  - Hub: Central Station
    - Nearby: High Speed Rail Terminal
    - Nearby: Metro Concourse
    - Nearby: Taxi Loop
    - Nearby: Intercity Bus Terminal
