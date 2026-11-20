Feature: Boarding reservation listing
  Reservations can be listed, optionally filtered by query parameters.

  Scenario: Listing reservations returns a collection
    When boarding reservations are listed without filters
    Then the reservation listing succeeds
    And the reservation listing body is a JSON array

  Scenario Outline: Listing reservations with filter <name> succeeds
    When boarding reservations are listed with query parameter "<name>" set to "<value>"
    Then the reservation listing succeeds

    Examples:
      | name       | value |
      | minNights  | 1     |
      | recentOnly | true  |

  Scenario: The minimum nights filter only returns long enough stays
    Given a boarding reservation for listing with 4 nights exists
    When boarding reservations are listed with query parameter "minNights" set to "4"
    Then the reservation listing succeeds
    And every listed reservation has at least 4 nights
    And the listed reservations include the one just created

  Scenario: Listing reservations with an unknown price tier is rejected
    When boarding reservations are listed with query parameter "tier" set to "NO_SUCH_TIER"
    Then the reservation listing is rejected with a client error
