Feature: Reservation listing and filtering
  Boarding reservations can be listed and filtered by minimum nights, recency and price tier.

  Scenario: Listing boarding reservations includes a newly created reservation
    Given a listed boarding reservation for a unique pet staying 2 nights
    When the client lists boarding reservations without filters
    Then the boarding reservation list returns status 200
    And the boarding reservation list contains the newly created reservation

  Scenario: Minimum nights filter keeps a reservation that is long enough
    Given a listed boarding reservation for a unique pet staying 6 nights
    When the client lists boarding reservations with minimum nights 5
    Then the boarding reservation list returns status 200
    And the boarding reservation list contains the newly created reservation

  Scenario: Minimum nights filter drops a reservation that is too short
    Given a listed boarding reservation for a unique pet staying 2 nights
    When the client lists boarding reservations with minimum nights 3
    Then the boarding reservation list returns status 200
    And the boarding reservation list does not contain the newly created reservation

  Scenario: Listing only recent boarding reservations succeeds
    Given a listed boarding reservation for a unique pet staying 2 nights
    When the client lists only recent boarding reservations
    Then the boarding reservation list returns status 200

  Scenario: Listing boarding reservations with an unknown price tier is rejected
    When the client lists boarding reservations with price tier "NOT_A_REAL_TIER"
    Then the boarding reservation list returns status 400
