Feature: Boarding reservation lifecycle

  Scenario: Create a reservation and read it back
    Given a new boarding reservation has been created
    When the boarding reservation is fetched by its id
    Then the fetched boarding reservation matches the submitted pet name and owner email

  Scenario: Update the number of nights of a reservation
    Given a new boarding reservation has been created
    When the boarding reservation is updated to 5 nights
    Then the boarding reservation update succeeds
    And fetching the boarding reservation shows 5 nights

  Scenario: Delete a reservation
    Given a new boarding reservation has been created
    When the boarding reservation is deleted
    Then the boarding reservation deletion succeeds
    And fetching the deleted boarding reservation returns status 404

  Scenario: Created reservation appears in the reservation list
    Given a new boarding reservation has been created
    When the boarding reservation list is requested
    Then the boarding reservation list contains the created pet name

  Scenario Outline: Filter the reservation list by a query parameter
    Given a new boarding reservation has been created
    When the boarding reservation list is requested with query parameter "<param>" set to "<value>"
    Then the boarding reservation list request returns status 200

    Examples:
      | param      | value |
      | minNights  | 1     |
      | recentOnly | true  |

  Scenario: Create a reservation with the WELCOME10 promo code
    Given a boarding reservation with promo code "WELCOME10" has been created
    When the boarding reservation is fetched by its id
    Then the boarding reservation fetch returns status 200
