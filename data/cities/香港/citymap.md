# City Map

@river: 香港 River | path=0.05,0.24;0.18,0.30;0.38,0.27;0.56,0.33;0.78,0.28;0.95,0.35 | width=0.08
@node: Central Block | kind=hub | district=Central Block | category=residential | x=2.5 | y=3.2
@node: North Block | kind=hub | district=North Block | category=residential | x=5.6 | y=3.2
@node: Hill Block | kind=hub | district=Hill Block | category=residential | x=8.7 | y=3.2
@node: East Block | kind=hub | district=East Block | category=residential | x=11.8 | y=3.2
@node: Lake Block | kind=hub | district=Lake Block | category=residential | x=14.9 | y=3.2
@node: South Block | kind=hub | district=South Block | category=residential | x=2.5 | y=5.8
@node: Central Station | kind=hub | district=Central Station | category=transit | x=5.6 | y=5.8
@node: Waterfront | kind=hub | district=Waterfront | category=leisure | x=8.7 | y=5.8
@node: Riverside Park | kind=hub | district=Riverside Park | category=leisure | x=11.8 | y=5.8
@node: Stadium | kind=hub | district=Stadium | category=leisure | x=14.9 | y=5.8
@node: Airport District | kind=hub | district=Airport District | category=transit | x=2.5 | y=8.4
@node: Financial District | kind=hub | district=Financial District | category=commerce | x=5.6 | y=8.4
@node: City Hall | kind=hub | district=City Hall | category=government | x=8.7 | y=8.4
@node: Night Market | kind=hub | district=Night Market | category=commerce | x=11.8 | y=8.4
@node: Industrial Park | kind=hub | district=Industrial Park | category=industry | x=14.9 | y=8.4
@node: Greenbelt Corridor | kind=hub | district=Greenbelt Corridor | category=leisure | x=2.5 | y=11.0
@node: Logistics Hub | kind=hub | district=Logistics Hub | category=industry | x=5.6 | y=11.0
@node: Medical Center | kind=hub | district=Medical Center | category=medical | x=8.7 | y=11.0
@road: Central Block -> North Block | type=arterial
@road: North Block -> Hill Block | type=arterial
@road: Hill Block -> East Block | type=arterial
@road: East Block -> Lake Block | type=arterial
@road: Lake Block -> South Block | type=arterial
@road: South Block -> Central Station | type=arterial
@road: Central Station -> Waterfront | type=arterial
@road: Waterfront -> Riverside Park | type=arterial
@road: Riverside Park -> Stadium | type=arterial
@road: Stadium -> Airport District | type=arterial
@road: Airport District -> Financial District | type=arterial
@road: Financial District -> City Hall | type=arterial
@road: City Hall -> Night Market | type=arterial
@road: Night Market -> Industrial Park | type=arterial
@road: Industrial Park -> Greenbelt Corridor | type=arterial
@road: Greenbelt Corridor -> Logistics Hub | type=arterial
@road: Logistics Hub -> Medical Center | type=arterial
@road: Medical Center -> Central Block | type=collector
@metro: M1 | color=#8f5bd8 | stops=Central Block>North Block>Hill Block>East Block>Lake Block>South Block

- City: 香港
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
        - Flat: 1C
      - Floor: 2F
        - Flat: 2A
        - Flat: 2B
        - Flat: 2C
    - Nearby: Building C-03
      - Floor: 1F
        - Flat: 1A
        - Flat: 1B
      - Floor: 2F
        - Flat: 2A
        - Flat: 2B
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
        - Flat: 1C
      - Floor: 2F
        - Flat: 2A
        - Flat: 2B
        - Flat: 2C
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
      - Floor: 3F
        - Flat: 3A
        - Flat: 3B
        - Flat: 3C
      - Floor: 4F
        - Flat: 4A
        - Flat: 4B
        - Flat: 4C
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
    - Nearby: Building S-02
      - Floor: 1F
        - Flat: 1A
        - Flat: 1B
        - Flat: 1C
      - Floor: 2F
        - Flat: 2A
        - Flat: 2B
        - Flat: 2C
    - Nearby: Building S-03
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
  - Hub: Central Station
    - Nearby: High Speed Rail Terminal
    - Nearby: Metro Concourse
    - Nearby: Taxi Loop
    - Nearby: Intercity Bus Terminal
  - Hub: Waterfront
    - Nearby: Riverside Port
    - Nearby: Marina Pier
    - Nearby: Riverfront Promenade
    - Nearby: Boathouse
  - Hub: Riverside Park
    - Nearby: Riverwalk
    - Nearby: Playground
    - Nearby: Fitness Area
    - Nearby: Picnic Lawn
  - Hub: Stadium
    - Nearby: Stadium Plaza
    - Nearby: Aquatic Center
    - Nearby: Training Grounds
    - Nearby: Sports Clinic
  - Hub: Airport District
    - Nearby: International Airport
    - Nearby: Airport Cargo Terminal
    - Nearby: Airport Hotel
    - Nearby: Air Traffic Control
  - Hub: Financial District
    - Nearby: Finance Plaza
    - Nearby: Riverside Tower
    - Nearby: Insurance Center
    - Nearby: Business Hotel
  - Hub: City Hall
    - Nearby: Civic Square
    - Nearby: Public Services Center
    - Nearby: Archives Building
    - Nearby: Courthouse
  - Hub: Night Market
    - Nearby: Food Street
    - Nearby: Open Air Bazaar
    - Nearby: Corner Mart
    - Nearby: Cinema Alley
  - Hub: Industrial Park
    - Nearby: Manufacturing Zone A
    - Nearby: Manufacturing Zone B
    - Nearby: Logistics Yard
    - Nearby: Power Substation
    - Nearby: Freight Depot
  - Hub: Greenbelt Corridor
    - Nearby: Eco Trail
    - Nearby: Wetland Reserve
    - Nearby: Botanical Garden
    - Nearby: Outdoor Amphitheater
  - Hub: Logistics Hub
    - Nearby: Freight Station
    - Nearby: Cold Storage Facility
    - Nearby: Sorting Center
    - Nearby: Truck Stop
  - Hub: Medical Center
    - Nearby: General Hospital
    - Nearby: Emergency Department
    - Nearby: Pediatrics Department
    - Nearby: Pharmacy
