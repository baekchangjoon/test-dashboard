Feature: Querying boarding reservations

  Scenario: Requesting an unknown boarding reservation returns not found
    When the boarding reservation with an unknown id is requested
    Then the boarding reservation query responds with status 404

  Scenario: Listing boarding reservations succeeds
    Given a boarding reservation for listing exists with 2 nights
    When boarding reservations are listed
    Then the boarding reservation query responds with status 200

  Scenario Outline: Listing boarding reservations with filter <name> succeeds
    Given a boarding reservation for listing exists with 2 nights
    When boarding reservations are listed with query parameter "<name>" set to "<value>"
    Then the boarding reservation query responds with status 200

    Examples:
      | name       | value |
      | minNights  | 1     |
      | recentOnly | true  |

  Scenario: Filtering boarding reservations by minimum nights includes a matching reservation
    Given a boarding reservation for listing exists with 14 nights
    When boarding reservations are listed with query parameter "minNights" set to "14"
    Then the boarding reservation query responds with status 200
    And the boarding reservation list contains the created pet name

  Scenario: Listing boarding reservations with an unknown price tier is rejected
    When boarding reservations are listed with query parameter "tier" set to "NOT_A_REAL_TIER"
    Then the boarding reservation query responds with status 400
