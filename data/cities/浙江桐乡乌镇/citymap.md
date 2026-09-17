# City Map

@river: 浙江桐乡乌镇 River | path=0.05,0.24;0.18,0.30;0.38,0.27;0.56,0.33;0.78,0.28;0.95,0.35 | width=0.08
@node: East Block | kind=hub | district=East Block | category=residential | x=2.5 | y=3.2
@node: South Block | kind=hub | district=South Block | category=residential | x=5.6 | y=3.2
@node: Central Block | kind=hub | district=Central Block | category=residential | x=8.7 | y=3.2
@node: Lake Block | kind=hub | district=Lake Block | category=residential | x=11.8 | y=3.2
@node: Old Town | kind=hub | district=Old Town | category=commerce | x=2.5 | y=5.8
@node: Night Market | kind=hub | district=Night Market | category=commerce | x=5.6 | y=5.8
@node: Stadium | kind=hub | district=Stadium | category=leisure | x=8.7 | y=5.8
@node: Medical Center | kind=hub | district=Medical Center | category=medical | x=11.8 | y=5.8
@node: Central Station | kind=hub | district=Central Station | category=transit | x=2.5 | y=8.4
@road: East Block -> South Block | type=arterial
@road: South Block -> Central Block | type=arterial
@road: Central Block -> Lake Block | type=arterial
@road: Lake Block -> Old Town | type=arterial
@road: Old Town -> Night Market | type=arterial
@road: Night Market -> Stadium | type=arterial
@road: Stadium -> Medical Center | type=arterial
@road: Medical Center -> Central Station | type=arterial
@road: Central Station -> East Block | type=collector

- City: 浙江桐乡乌镇
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
        - Flat: 1C
      - Floor: 2F
        - Flat: 2A
        - Flat: 2B
        - Flat: 2C
      - Floor: 3F
        - Flat: 3A
        - Flat: 3B
        - Flat: 3C
    - Nearby: Building E-03
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
    - Nearby: Building L-02
      - Floor: 1F
        - Flat: 1A
        - Flat: 1B
        - Flat: 1C
      - Floor: 2F
        - Flat: 2A
        - Flat: 2B
        - Flat: 2C
    - Nearby: Building L-03
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
  - Hub: Stadium
    - Nearby: Stadium Plaza
    - Nearby: Aquatic Center
    - Nearby: Training Grounds
    - Nearby: Sports Clinic
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
