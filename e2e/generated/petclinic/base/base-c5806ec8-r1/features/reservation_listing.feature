Feature: Boarding reservation listing
  Reservations can be listed and filtered by query parameters.

  Scenario: Listing reservations succeeds
    When the client lists boarding reservations
    Then the reservation listing response has status 200

  Scenario: Filtering by minimum nights includes a matching reservation
    Given a boarding reservation with 5 nights has been created for listing
    When the client lists boarding reservations with query parameter minNights set to 3
    Then the reservation listing response has status 200
    And the reservation listing contains the created reservation

  Scenario: Listing only recent reservations succeeds
    When the client lists boarding reservations with query parameter recentOnly set to true
    Then the reservation listing response has status 200

  Scenario: Listing with an unknown price tier is rejected
    When the client lists boarding reservations with query parameter tier set to NOT_A_TIER
    Then the reservation listing response has status 400
