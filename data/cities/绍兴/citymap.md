# City Map

@river: 绍兴市 River | path=0.05,0.24;0.18,0.30;0.38,0.27;0.56,0.33;0.78,0.28;0.95,0.35 | width=0.08
@node: Lake Block | kind=hub | district=Lake Block | category=residential | x=2.5 | y=3.2
@node: Hill Block | kind=hub | district=Hill Block | category=residential | x=5.6 | y=3.2
@node: South Block | kind=hub | district=South Block | category=residential | x=8.7 | y=3.2
@node: Central Block | kind=hub | district=Central Block | category=residential | x=11.8 | y=3.2
@node: North Block | kind=hub | district=North Block | category=residential | x=14.9 | y=3.2
@node: West Block | kind=hub | district=West Block | category=residential | x=2.5 | y=5.8
@node: Medical Center | kind=hub | district=Medical Center | category=medical | x=5.6 | y=5.8
@node: Central Station | kind=hub | district=Central Station | category=transit | x=8.7 | y=5.8
@node: Greenbelt Corridor | kind=hub | district=Greenbelt Corridor | category=leisure | x=11.8 | y=5.8
@node: Airport District | kind=hub | district=Airport District | category=transit | x=14.9 | y=5.8
@node: Old Town | kind=hub | district=Old Town | category=commerce | x=2.5 | y=8.4
@node: Night Market | kind=hub | district=Night Market | category=commerce | x=5.6 | y=8.4
@node: Riverside Park | kind=hub | district=Riverside Park | category=leisure | x=8.7 | y=8.4
@node: Tech Park | kind=hub | district=Tech Park | category=commerce | x=11.8 | y=8.4
@node: University District | kind=hub | district=University District | category=education | x=14.9 | y=8.4
@node: Industrial Park | kind=hub | district=Industrial Park | category=industry | x=2.5 | y=11.0
@node: City Hall | kind=hub | district=City Hall | category=government | x=5.6 | y=11.0
@node: Stadium | kind=hub | district=Stadium | category=leisure | x=8.7 | y=11.0
@road: Lake Block -> Hill Block | type=arterial
@road: Hill Block -> South Block | type=arterial
@road: South Block -> Central Block | type=arterial
@road: Central Block -> North Block | type=arterial
@road: North Block -> West Block | type=arterial
@road: West Block -> Medical Center | type=arterial
@road: Medical Center -> Central Station | type=arterial
@road: Central Station -> Greenbelt Corridor | type=arterial
@road: Greenbelt Corridor -> Airport District | type=arterial
@road: Airport District -> Old Town | type=arterial
@road: Old Town -> Night Market | type=arterial
@road: Night Market -> Riverside Park | type=arterial
@road: Riverside Park -> Tech Park | type=arterial
@road: Tech Park -> University District | type=arterial
@road: University District -> Industrial Park | type=arterial
@road: Industrial Park -> City Hall | type=arterial
@road: City Hall -> Stadium | type=arterial
@road: Stadium -> Lake Block | type=collector
@metro: M1 | color=#8f5bd8 | stops=Lake Block>Hill Block>South Block>Central Block>North Block>West Block

- City: 绍兴市
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
      - Floor: 4F
        - Flat: 4A
        - Flat: 4B
        - Flat: 4C
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
      - Floor: 2F
        - Flat: 2A
        - Flat: 2B
      - Floor: 3F
        - Flat: 3A
        - Flat: 3B
      - Floor: 4F
        - Flat: 4A
        - Flat: 4B
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
  - Hub: South Block
    - Nearby: Building S-01
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
    - Nearby: Building S-02
      - Floor: 1F
        - Flat: 1A
        - Flat: 1B
      - Floor: 2F
        - Flat: 2A
        - Flat: 2B
    - Nearby: Building S-03
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
    - Nearby: Building C-02
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
  - Hub: North Block
    - Nearby: Building N-01
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
    - Nearby: Building N-02
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
      - Floor: 4F
        - Flat: 4A
        - Flat: 4B
    - Nearby: Building W-03
      - Floor: 1F
        - Flat: 1A
        - Flat: 1B
      - Floor: 2F
        - Flat: 2A
        - Flat: 2B
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
  - Hub: Greenbelt Corridor
    - Nearby: Eco Trail
    - Nearby: Wetland Reserve
    - Nearby: Botanical Garden
    - Nearby: Outdoor Amphitheater
  - Hub: Airport District
    - Nearby: International Airport
    - Nearby: Airport Cargo Terminal
    - Nearby: Airport Hotel
    - Nearby: Air Traffic Control
  - Hub: Old Town
    - Nearby: Old Town Market
    - Nearby: Heritage Street
    - Nearby: Temple Square
    - Nearby: Tea House Alley
    - Nearby: City Museum
  - Hub: Night Market
    - Nearby: Food Street
    - Nearby: Open Air Bazaar
    - Nearby: Corner Mart
    - Nearby: Cinema Alley
  - Hub: Riverside Park
    - Nearby: Riverwalk
    - Nearby: Playground
    - Nearby: Fitness Area
    - Nearby: Picnic Lawn
  - Hub: Tech Park
    - Nearby: R&D Center
    - Nearby: Innovation Hub
    - Nearby: Admin Office
    - Nearby: Startup Incubator
  - Hub: University District
    - Nearby: Main Library
    - Nearby: Engineering Building
    - Nearby: Arts Building
    - Nearby: Dormitory A
    - Nearby: Dormitory B
    - Nearby: Student Canteen
  - Hub: Industrial Park
    - Nearby: Manufacturing Zone A
    - Nearby: Manufacturing Zone B
    - Nearby: Logistics Yard
    - Nearby: Power Substation
    - Nearby: Freight Depot
  - Hub: City Hall
    - Nearby: Civic Square
    - Nearby: Public Services Center
    - Nearby: Archives Building
    - Nearby: Courthouse
  - Hub: Stadium
    - Nearby: Stadium Plaza
    - Nearby: Aquatic Center
    - Nearby: Training Grounds
    - Nearby: Sports Clinic
