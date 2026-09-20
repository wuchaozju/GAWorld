# City Map

@river: 乌镇 River | path=0.05,0.24;0.18,0.30;0.38,0.27;0.56,0.33;0.78,0.28;0.95,0.35 | width=0.08
@node: Hill Block | kind=hub | district=Hill Block | category=residential | x=2.5 | y=3.2
@node: North Block | kind=hub | district=North Block | category=residential | x=5.6 | y=3.2
@node: East Block | kind=hub | district=East Block | category=residential | x=8.7 | y=3.2
@node: South Block | kind=hub | district=South Block | category=residential | x=11.8 | y=3.2
@node: Greenbelt Corridor | kind=hub | district=Greenbelt Corridor | category=leisure | x=2.5 | y=5.8
@node: Night Market | kind=hub | district=Night Market | category=commerce | x=5.6 | y=5.8
@node: Riverside Park | kind=hub | district=Riverside Park | category=leisure | x=8.7 | y=5.8
@node: University District | kind=hub | district=University District | category=education | x=11.8 | y=5.8
@node: Waterfront | kind=hub | district=Waterfront | category=leisure | x=2.5 | y=8.4
@road: Hill Block -> North Block | type=arterial
@road: North Block -> East Block | type=arterial
@road: East Block -> South Block | type=arterial
@road: South Block -> Greenbelt Corridor | type=arterial
@road: Greenbelt Corridor -> Night Market | type=arterial
@road: Night Market -> Riverside Park | type=arterial
@road: Riverside Park -> University District | type=arterial
@road: University District -> Waterfront | type=arterial
@road: Waterfront -> Hill Block | type=collector

- City: 乌镇
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
      - Floor: 3F
        - Flat: 3A
        - Flat: 3B
      - Floor: 4F
        - Flat: 4A
        - Flat: 4B
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
        - Flat: 1C
      - Floor: 2F
        - Flat: 2A
        - Flat: 2B
        - Flat: 2C
      - Floor: 3F
        - Flat: 3A
        - Flat: 3B
        - Flat: 3C
    - Nearby: Building S-03
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
  - Hub: Greenbelt Corridor
    - Nearby: Eco Trail
    - Nearby: Wetland Reserve
    - Nearby: Botanical Garden
    - Nearby: Outdoor Amphitheater
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
