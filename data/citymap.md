# Village Map

@river: Qiantang River | path=0.04,0.26;0.18,0.31;0.34,0.27;0.52,0.33;0.7,0.28;0.92,0.34 | width=0.09
@node: North Block | kind=hub | district=North Residential | category=residential | x=2.8 | y=3.2
@node: Central Block | kind=hub | district=Central Residential | category=residential | x=5.8 | y=4.5
@node: South Block | kind=hub | district=South Residential | category=residential | x=6.2 | y=7.3
@node: East Block | kind=hub | district=East Residential | category=residential | x=9.4 | y=4.8
@node: West Block | kind=hub | district=West Residential | category=residential | x=2.4 | y=6.0
@node: University District | kind=hub | district=University District | category=education | x=10.8 | y=2.9
@node: Financial District | kind=hub | district=CBD | category=commerce | x=8.7 | y=6.1
@node: Industrial Park | kind=hub | district=Industry Belt | category=industry | x=12.8 | y=7.5
@node: Logistics Hub | kind=hub | district=Logistics Belt | category=industry | x=12.2 | y=5.4
@node: City Hall | kind=hub | district=Civic Center | category=government | x=7.1 | y=5.1
@node: Riverside Stadium | kind=hub | district=River Sports Zone | category=leisure | x=9.9 | y=7.3
@node: Central Station | kind=hub | district=Transit Core | category=transit | x=7.8 | y=3.4
@node: Airport District | kind=hub | district=Airport Corridor | category=transit | x=14.2 | y=3.1
@node: Waterfront | kind=hub | district=Waterfront | category=leisure | x=11.8 | y=1.8
@node: Riverside Bus Station | kind=hub | district=Transit Core | category=transit | x=5.2 | y=2.8
@road: North Block -> Central Block | type=collector
@road: Central Block -> South Block | type=arterial
@road: Central Block -> City Hall | type=arterial
@road: Central Block -> Riverside Bus Station | type=collector
@road: Riverside Bus Station -> Central Station | type=arterial | bridge=true
@road: Central Station -> Financial District | type=arterial
@road: Financial District -> Riverside Stadium | type=collector
@road: Financial District -> Logistics Hub | type=arterial
@road: Logistics Hub -> Industrial Park | type=arterial
@road: Central Station -> Airport District | type=arterial
@road: University District -> Central Station | type=arterial
@road: Waterfront -> Central Station | type=collector | bridge=true
@metro: M1 | color=#8f5bd8 | stops=North Block>Central Block>Riverside Bus Station>Central Station>Financial District>Airport District
@metro: M2 | color=#2b9ccf | stops=University District>Central Station>City Hall>Riverside Stadium>Waterfront

- Village: Hangzhou Riverside Village
  - Hub: C-01 (Village Center)
    - Nearby: C-02
    - Nearby: Riverside Public Library
    - Nearby: Hangzhou Riverside Community Center
    - Nearby: Riverside Bank Branch
    - Nearby: Central Parking Lot
    - Nearby: Market St
    - Nearby: East Loop
  - Hub: Riverside Park
    - Nearby: Riverwalk
    - Nearby: Playground
    - Nearby: Fitness Area
    - Nearby: Riverside Cinema
    - Nearby: Riverside Bus Station
    - Nearby: Riverside Ave
    - Nearby: Bridge Rd
  - Hub: Riverside Community Hospital
    - Nearby: Emergency Department
    - Nearby: Pediatrics Department
    - Nearby: Cardiology Department
    - Nearby: Imaging Department
    - Nearby: Northside Family Clinic
    - Nearby: Willow Pharmacy
    - Nearby: Willow Rd
  - Hub: Riverside Bus Station
    - Nearby: Riverside Post Office
    - Nearby: Riverside Police Station
    - Nearby: Riverside Fire Station
    - Nearby: Corner Mart
    - Nearby: West Loop
  - Hub: Hangzhou Tech Labs
    - Nearby: RnD Center
    - Nearby: Admin Office
    - Nearby: Riverside Logistics
    - Nearby: Warehouse A
    - Nearby: Warehouse B
    - Nearby: Bridge Construction Co.
  - Hub: Riverside Night Market
    - Nearby: Riverside Supermart
    - Nearby: Riverside Cinema
    - Nearby: Corner Mart
    - Nearby: Market St
  - Hub: Willow Grove Park
    - Nearby: Basketball Court
    - Nearby: Picnic Area
    - Nearby: East Pocket Park
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
    - Nearby: Riverside Primary School
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
    - Nearby: Riverside Middle School
    - Nearby: Little River Daycare
  - Hub: South Block
    - Nearby: Building S-01
      - Floor: 1F
        - Flat: 1A
        - Flat: 1B
      - Floor: 2F
        - Flat: 2A
        - Flat: 2B
      - Floor: 3F
        - Flat: 3A
        - Flat: 3B
    - Nearby: Building S-02
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
    - Nearby: Willow Design Studio
  - Hub: East Block
    - Nearby: Building E-01
      - Floor: 1F
        - Flat: 1A
        - Flat: 1B
      - Floor: 2F
        - Flat: 2A
        - Flat: 2B
      - Floor: 3F
        - Flat: 3A
        - Flat: 3B
    - Nearby: Building E-02
      - Floor: 1F
        - Flat: 1A
        - Flat: 1B
      - Floor: 2F
        - Flat: 2A
        - Flat: 2B
    - Nearby: East Community Clinic
    - Nearby: East Pocket Park
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
      - Floor: 2F
        - Flat: 2A
        - Flat: 2B
    - Nearby: Westside Community Center
    - Nearby: Westside Playground
  - Hub: University District
    - Nearby: Riverside University Gate
    - Nearby: Main Library
    - Nearby: Engineering Building
    - Nearby: Arts Building
    - Nearby: Dormitory A
    - Nearby: Dormitory B
    - Nearby: Student Canteen
  - Hub: Old Town
    - Nearby: Old Town Market
    - Nearby: Heritage Street
    - Nearby: Temple Square
    - Nearby: Tea House Alley
    - Nearby: Riverside Museum
  - Hub: Financial District
    - Nearby: Riverside Tower
    - Nearby: Finance Plaza
    - Nearby: Insurance Center
    - Nearby: Central Bank Annex
    - Nearby: Business Hotel
  - Hub: Industrial Park
    - Nearby: Manufacturing Zone A
    - Nearby: Manufacturing Zone B
    - Nearby: Logistics Yard
    - Nearby: Power Substation
    - Nearby: Freight Depot
  - Hub: Logistics Hub
    - Nearby: Riverside Freight Station
    - Nearby: Cold Storage Facility
    - Nearby: Sorting Center
    - Nearby: Long Haul Truck Stop
  - Hub: Riverside Stadium
    - Nearby: Stadium Plaza
    - Nearby: Aquatic Center
    - Nearby: Training Grounds
    - Nearby: Sports Clinic
  - Hub: City Hall
    - Nearby: Civic Square
    - Nearby: Public Services Center
    - Nearby: Archives Building
    - Nearby: Courthouse
  - Hub: Central Station
    - Nearby: High Speed Rail Terminal
    - Nearby: Metro Concourse
    - Nearby: Taxi Loop
    - Nearby: Intercity Bus Terminal
  - Hub: Airport District
    - Nearby: Riverside International Airport
    - Nearby: Airport Cargo Terminal
    - Nearby: Airport Hotel
    - Nearby: Air Traffic Control
  - Hub: Waterfront
    - Nearby: Riverside Port
    - Nearby: Marina Pier
    - Nearby: Riverfront Promenade
    - Nearby: Boathouse
  - Hub: Hillside District
    - Nearby: Hillside Park
    - Nearby: Scenic Overlook
    - Nearby: Mountain Trailhead
    - Nearby: Hillside Clinic
  - Hub: Greenbelt Corridor
    - Nearby: Eco Trail
    - Nearby: Wetland Reserve
    - Nearby: Botanical Garden
    - Nearby: Outdoor Amphitheater
