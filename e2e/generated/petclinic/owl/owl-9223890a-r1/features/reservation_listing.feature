Feature: Boarding reservation listing and filters

  Scenario: Listing reservations includes a freshly booked reservation
    Given the listing client has booked a reservation for 3 nights
    When the listing client lists all reservations
    Then the listing response status is 200
    And the listing response mentions the booked pet name

  Scenario: Filter reservations by a minimum number of nights
    Given the listing client has booked a reservation for 5 nights
    When the listing client lists reservations with query parameter "minNights" set to "1"
    Then the listing response status is 200
    And the listing response mentions the booked pet name

  Scenario: Filter reservations to recent ones only
    Given the listing client has booked a reservation for 2 nights
    When the listing client lists reservations with query parameter "recentOnly" set to "true"
    Then the listing response status is 200

  Scenario: Filter reservations by the price tier of a booked reservation
    Given the listing client has booked a reservation for 2 nights
    When the listing client lists reservations filtered by the booked price tier
    Then the listing response status is 200
    And the listing response mentions the booked pet name

  Scenario: Reject an unknown price tier filter
    When the listing client lists reservations with query parameter "tier" set to "NO_SUCH_TIER_XYZ"
    Then the listing response status is 400
