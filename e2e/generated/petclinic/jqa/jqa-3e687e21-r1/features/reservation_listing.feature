Feature: Boarding reservation listing

  Scenario: The reservation list includes a newly created reservation
    Given a boarding reservation for listing has been created
    When the client lists boarding reservations
    Then the reservation listing responds with status 200
    And the listing includes the created reservation pet name

  Scenario Outline: Listing reservations with a filter succeeds
    Given a boarding reservation for listing has been created
    When the client lists boarding reservations filtered by "<param>" equal to "<value>"
    Then the reservation listing responds with status 200

    Examples:
      | param      | value |
      | minNights  | 1     |
      | recentOnly | true  |
