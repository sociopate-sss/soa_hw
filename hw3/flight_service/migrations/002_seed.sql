-- Seed data: sample flights

INSERT INTO flights (flight_number, airline, origin, destination, departure_time, arrival_time, departure_date, total_seats, available_seats, price, status)
VALUES
    ('SU1234', 'Aeroflot',    'SVO', 'LED', '2026-04-01 10:00:00+03', '2026-04-01 11:30:00+03', '2026-04-01', 180, 180, 5500.00, 'SCHEDULED'),
    ('SU1235', 'Aeroflot',    'LED', 'SVO', '2026-04-01 14:00:00+03', '2026-04-01 15:30:00+03', '2026-04-01', 180, 180, 5500.00, 'SCHEDULED'),
    ('S72001', 'S7 Airlines', 'DME', 'LED', '2026-04-01 08:00:00+03', '2026-04-01 09:30:00+03', '2026-04-01', 120, 120, 4200.00, 'SCHEDULED'),
    ('DP405',  'Pobeda',      'VKO', 'AER', '2026-04-02 06:00:00+03', '2026-04-02 08:30:00+03', '2026-04-02', 189, 189, 2999.00, 'SCHEDULED'),
    ('SU505',  'Aeroflot',    'SVO', 'AER', '2026-04-02 12:00:00+03', '2026-04-02 14:30:00+03', '2026-04-02', 180, 180, 7500.00, 'SCHEDULED'),
    ('N4123',  'Nordwind',    'SVO', 'AER', '2026-04-02 16:00:00+03', '2026-04-02 18:30:00+03', '2026-04-02', 200, 200, 6100.00, 'SCHEDULED'),
    ('SU300',  'Aeroflot',    'SVO', 'LED', '2026-04-02 09:00:00+03', '2026-04-02 10:30:00+03', '2026-04-02', 180, 180, 5800.00, 'SCHEDULED'),
    ('DP210',  'Pobeda',      'VKO', 'LED', '2026-04-01 07:00:00+03', '2026-04-01 08:40:00+03', '2026-04-01', 189, 189, 2499.00, 'SCHEDULED')
ON CONFLICT DO NOTHING;
