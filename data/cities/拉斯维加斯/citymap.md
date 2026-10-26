# City Map

@river: 拉斯维加斯;拉斯維加斯 River | path=0.05,0.24;0.18,0.30;0.38,0.27;0.56,0.33;0.78,0.28;0.95,0.35 | width=0.08
@node: Central Block | kind=hub | district=Central Block | category=residential | x=2.5 | y=3.2
@node: Lake Block | kind=hub | district=Lake Block | category=residential | x=5.6 | y=3.2
@node: East Block | kind=hub | district=East Block | category=residential | x=8.7 | y=3.2
@node: West Block | kind=hub | district=West Block | category=residential | x=11.8 | y=3.2
@node: Hill Block | kind=hub | district=Hill Block | category=residential | x=14.9 | y=3.2
@node: North Block | kind=hub | district=North Block | category=residential | x=2.5 | y=5.8
@node: Medical Center | kind=hub | district=Medical Center | category=medical | x=5.6 | y=5.8
@node: Central Station | kind=hub | district=Central Station | category=transit | x=8.7 | y=5.8
@node: Night Market | kind=hub | district=Night Market | category=commerce | x=11.8 | y=5.8
@node: Logistics Hub | kind=hub | district=Logistics Hub | category=industry | x=14.9 | y=5.8
@node: Old Town | kind=hub | district=Old Town | category=commerce | x=2.5 | y=8.4
@node: University District | kind=hub | district=University District | category=education | x=5.6 | y=8.4
@node: Waterfront | kind=hub | district=Waterfront | category=leisure | x=8.7 | y=8.4
@node: Airport District | kind=hub | district=Airport District | category=transit | x=11.8 | y=8.4
@node: Industrial Park | kind=hub | district=Industrial Park | category=industry | x=14.9 | y=8.4
@node: Tech Park | kind=hub | district=Tech Park | category=commerce | x=2.5 | y=11.0
@node: Greenbelt Corridor | kind=hub | district=Greenbelt Corridor | category=leisure | x=5.6 | y=11.0
@node: Stadium | kind=hub | district=Stadium | category=leisure | x=8.7 | y=11.0
@road: Central Block -> Lake Block | type=arterial
@road: Lake Block -> East Block | type=arterial
@road: East Block -> West Block | type=arterial
@road: West Block -> Hill Block | type=arterial
@road: Hill Block -> North Block | type=arterial
@road: North Block -> Medical Center | type=arterial
@road: Medical Center -> Central Station | type=arterial
@road: Central Station -> Night Market | type=arterial
@road: Night Market -> Logistics Hub | type=arterial
@road: Logistics Hub -> Old Town | type=arterial
@road: Old Town -> University District | type=arterial
@road: University District -> Waterfront | type=arterial
@road: Waterfront -> Airport District | type=arterial
@road: Airport District -> Industrial Park | type=arterial
@road: Industrial Park -> Tech Park | type=arterial
@road: Tech Park -> Greenbelt Corridor | type=arterial
@road: Greenbelt Corridor -> Stadium | type=arterial
@road: Stadium -> Central Block | type=collector
@metro: M1 | color=#8f5bd8 | stops=Central Block>Lake Block>East Block>West Block>Hill Block>North Block

- City: 拉斯维加斯;拉斯維加斯
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
      - Floor: 4F
        - Flat: 4A
        - Flat: 4B
    - Nearby: Building C-03
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
    - Nearby: Building E-03
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
      - Floor: 3F
        - Flat: 3A
        - Flat: 3B
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
      - Floor: 4F
        - Flat: 4A
        - Flat: 4B
        - Flat: 4C
    - Nearby: Building W-03
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
      - Floor: 4F
        - Flat: 4A
        - Flat: 4B
        - Flat: 4C
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
    - Nearby: Neighborhood Clinic
    - Nearby: Pocket Park
  - Hub: North Block
    - Nearby: Building N-01
      - Floor: 1F
        - Flat: 1A
        - Flat: 1B
      - Floor: 2F
        - Flat: 2A
        - Flat: 2B
      - Floor: 3F
        - Flat: 3A
        - Flat: 3B
    - Nearby: Building N-02
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
    - Nearby: Building N-03
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
  - Hub: Medical Center
    - Nearby: General Hospital
    - Nearby: Emergency Department
    - Nearby: Pediatrics Department
    - Nearby: Pharmacy
  - Hub: Central Station
    - Nearby: High Speed Rail Terminal
    - Nearby: Metro Concourse
    - Nearby: Taxi Loop
    - Nearby: Intercity Bus Terminal
  - Hub: Night Market
    - Nearby: Food Street
    - Nearby: Open Air Bazaar
    - Nearby: Corner Mart
    - Nearby: Cinema Alley
  - Hub: Logistics Hub
    - Nearby: Freight Station
    - Nearby: Cold Storage Facility
    - Nearby: Sorting Center
    - Nearby: Truck Stop
  - Hub: Old Town
    - Nearby: Old Town Market
    - Nearby: Heritage Street
    - Nearby: Temple Square
    - Nearby: Tea House Alley
    - Nearby: City Museum
  - Hub: University District
    - Nearby: Main Library
    - Nearby: Engineering Building
    - Nearby: Arts Building
    - Nearby: Dormitory A
    - Nearby: Dormitory B
    - Nearby: Student Canteen
  - Hub: Waterfront
    - Nearby: Riverside Port
    - Nearby: Marina Pier
    - Nearby: Riverfront Promenade
    - Nearby: Boathouse
  - Hub: Airport District
    - Nearby: International Airport
    - Nearby: Airport Cargo Terminal
    - Nearby: Airport Hotel
    - Nearby: Air Traffic Control
  - Hub: Industrial Park
    - Nearby: Manufacturing Zone A
    - Nearby: Manufacturing Zone B
    - Nearby: Logistics Yard
    - Nearby: Power Substation
    - Nearby: Freight Depot
  - Hub: Tech Park
    - Nearby: R&D Center
    - Nearby: Innovation Hub
    - Nearby: Admin Office
    - Nearby: Startup Incubator
  - Hub: Greenbelt Corridor
    - Nearby: Eco Trail
    - Nearby: Wetland Reserve
    - Nearby: Botanical Garden
    - Nearby: Outdoor Amphitheater
  - Hub: Stadium
    - Nearby: Stadium Plaza
    - Nearby: Aquatic Center
    - Nearby: Training Grounds
    - Nearby: Sports Clinic
