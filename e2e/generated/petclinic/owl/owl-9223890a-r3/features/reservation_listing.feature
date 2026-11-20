Feature: Boarding reservation listing
  Reservations can be listed and filtered with query parameters.

  Scenario: Listing reservations includes a newly created reservation
    Given a boarding reservation with 2 nights has been created for listing
    When all boarding reservations are listed
    Then the reservation listing response status is 200
    And the reservation listing contains the created reservation

  Scenario: Filtering reservations by minimum nights
    Given a boarding reservation with 6 nights has been created for listing
    When boarding reservations are listed with query parameter "minNights" set to "6"
    Then the reservation listing response status is 200
    And the reservation listing contains the created reservation
    And every listed reservation has at least 6 nights

  Scenario: Listing only recent reservations succeeds
    Given a boarding reservation with 2 nights has been created for listing
    When boarding reservations are listed with query parameter "recentOnly" set to "true"
    Then the reservation listing response status is 200

  Scenario: Filtering reservations by an unknown price tier is rejected
    When boarding reservations are listed with query parameter "tier" set to "NOT_A_TIER"
    Then the reservation listing response status is 400
