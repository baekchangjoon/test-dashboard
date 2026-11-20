Feature: Boarding reservation search
  Reservations can be listed and filtered.

  Scenario: Listing reservations includes a newly created reservation
    Given a reservation with 5 nights exists for the search test
    When reservations are listed without filters
    Then the search response status is 200
    And the search results include the created pet name

  Scenario: Filtering reservations by minimum nights keeps a longer stay
    Given a reservation with 5 nights exists for the search test
    When reservations are listed with query parameter "minNights" set to "3"
    Then the search response status is 200
    And the search results include the created pet name

  Scenario: Listing only recent reservations succeeds
    Given a reservation with 5 nights exists for the search test
    When reservations are listed with query parameter "recentOnly" set to "true"
    Then the search response status is 200

  Scenario: A non-numeric minimum nights filter is rejected
    When reservations are listed with query parameter "minNights" set to "abc"
    Then the search response status is 400
