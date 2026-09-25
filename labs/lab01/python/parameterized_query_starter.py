"""Student starter: repair the vulnerable customer-name query."""

from db import connect


def find_orders_by_customer_name(name: str) -> list[tuple]:
    # TODO: Keep the SQL statement fixed and pass name as a bound value.
    query = """
        SELECT o.order_ref, o.status
        FROM lab01.orders AS o
        JOIN lab01.customers AS c ON c.id = o.customer_id
        WHERE c.full_name = %s
    """
    # TODO: Supply the value separately using Psycopg's parameter binding.
    parameters = (name,)

    with connect() as connection:
        return connection.execute(query, parameters).fetchall()


if __name__ == "__main__":
    supplied_name = input("Customer name: ")
    print(find_orders_by_customer_name(supplied_name))
