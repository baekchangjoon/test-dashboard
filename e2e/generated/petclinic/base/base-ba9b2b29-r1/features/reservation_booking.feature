Feature: Booking boarding reservations

  Scenario: A valid boarding reservation is created
    Given a unique boarding reservation request
    When the boarding reservation request is submitted
    Then the boarding reservation is accepted with an id

  Scenario: A created boarding reservation can be read back by id
    Given a unique boarding reservation request
    When the boarding reservation request is submitted
    Then the boarding reservation is accepted with an id
    When the created boarding reservation is fetched by id
    Then the fetched boarding reservation shows the submitted pet name and owner email

  Scenario: A boarding reservation with the WELCOME10 promo code is created
    Given a unique boarding reservation request with promo code "WELCOME10"
    When the boarding reservation request is submitted
    Then the boarding reservation is accepted with an id

  Scenario: An empty boarding reservation request is rejected
    When an empty boarding reservation request is submitted
    Then the boarding reservation submission fails with status 400

  Scenario Outline: A boarding reservation request with invalid <field> is rejected
    Given a unique boarding reservation request
    And the boarding reservation field "<field>" is set to "<value>"
    When the boarding reservation request is submitted
    Then the boarding reservation submission fails with status 400

    Examples:
      | field       | value      |
      | petName     |            |
      | nights      | 0          |
      | nights      | -1         |
      | checkInDate | 2000-01-01 |

  Scenario: A second boarding reservation for the same room and date is rejected as a conflict
    Given a boarding reservation already exists for a unique room and date
    When another boarding reservation is submitted for the same room and date
    Then the boarding reservation submission fails with status 409
