Feature: Boarding reservation listing
  Reservations can be listed with optional filters.

  Scenario: Listing reservations includes a freshly created reservation
    Given a reservation has been created for the search test
    When all reservations are listed
    Then the reservation search response status is 200
    And the reservation list contains the reservation created for the search test

  Scenario Outline: Listing reservations with filter parameters succeeds
    Given a reservation has been created for the search test
    When reservations are listed with query "<query>"
    Then the reservation search response status is 200

    Examples:
      | query                        |
      | minNights=1                  |
      | recentOnly=true              |
      | minNights=1&recentOnly=false |

  Scenario: Listing reservations with an unknown price tier is rejected
    When reservations are listed with query "tier=NOT_A_REAL_TIER"
    Then the reservation search response status is 400
