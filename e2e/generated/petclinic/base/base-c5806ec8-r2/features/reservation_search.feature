Feature: Boarding reservation listing and filters

  Scenario: List reservations
    Given a reservation created for the listing check with 2 nights
    When the listing client requests the reservation list
    Then the listing response status is 200
    And the listing response body is not empty

  Scenario: Filter reservations by minimum number of nights
    Given a reservation created for the listing check with 4 nights
    When the listing client requests reservations with minNights 4
    Then the listing response status is 200
    And the listing response mentions the created pet name

  Scenario: Filter reservations to recent ones only
    Given a reservation created for the listing check with 2 nights
    When the listing client requests only recent reservations
    Then the listing response status is 200
    And the listing response mentions the created pet name

  Scenario: Reject an unknown price tier filter
    When the listing client requests reservations with tier "NOT_A_REAL_TIER"
    Then the listing response status is 400
