"""Intentionally vulnerable example for local teaching only."""

from db import connect


def find_orders_by_customer_name(name: str) -> list[tuple]:
    # Deliberately unsafe: input is inserted into the SQL instructions.
    query = f"""
        SELECT o.order_ref, o.status
        FROM lab01.orders AS o
        JOIN lab01.customers AS c ON c.id = o.customer_id
        WHERE c.full_name = '{name}'
    """
    with connect() as connection:
        return connection.execute(query).fetchall()


if __name__ == "__main__":
    supplied_name = input("Customer name: ")
    print(find_orders_by_customer_name(supplied_name))
