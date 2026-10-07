"""SQLAlchemy models, bound queries and trusted application-role authorization."""
import argparse
import os
from pathlib import Path
from dotenv import load_dotenv
from sqlalchemy import String, ForeignKey, create_engine, select, text
from sqlalchemy.engine import URL
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, Session


class Base(DeclarativeBase):
    pass


class Customer(Base):
    __tablename__ = "lab05_customers"
    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(String(100))


class Order(Base):
    __tablename__ = "lab05_orders"
    id: Mapped[int] = mapped_column(primary_key=True)
    customer_id: Mapped[int] = mapped_column(ForeignKey("lab05_customers.id"))
    amount: Mapped[int]  # integer currency units for this exercise


PERMISSIONS = {"viewer": {"read"}, "analyst": {"read", "report"},
               "admin": {"read", "report", "write"}}


class QueryService:
    """Role must come from trusted authentication, never a client query parameter."""
    def __init__(self, session, role):
        self.session, self.role = session, role

    def authorize(self, action):
        if action not in PERMISSIONS.get(self.role, set()):
            raise PermissionError(f"{self.role!r} cannot perform {action!r}")

    def find_customer(self, name):
        self.authorize("read")
        return self.session.scalars(select(Customer).where(Customer.name == name)).all()

    def report(self, minimum):
        self.authorize("report")
        # Values are bound separately; SQL text is never constructed from user input.
        return self.session.execute(text(
            "SELECT c.name, o.amount FROM lab05_customers c "
            "JOIN lab05_orders o ON c.id = o.customer_id "
            "WHERE o.amount >= :minimum ORDER BY o.id"
        ), {"minimum": minimum}).all()

    def add_order(self, customer_id, amount):
        self.authorize("write")
        if amount < 0:
            raise ValueError("amount must be nonnegative")
        self.session.add(Order(customer_id=customer_id, amount=amount))
        self.session.flush()


def seed(engine):
    Base.metadata.create_all(engine)
    with Session(engine) as session, session.begin():
        if session.scalar(select(Customer.id).limit(1)) is None:
            session.add_all([Customer(id=1, name="Mona"), Customer(id=2, name="Ali")])
            session.flush()
            session.add_all([Order(id=1, customer_id=1, amount=100),
                             Order(id=2, customer_id=2, amount=250),
                             Order(id=3, customer_id=1, amount=400)])


def course_engine():
    load_dotenv(Path(__file__).resolve().parents[2] / ".env")
    return create_engine(URL.create(
        "postgresql+psycopg", username=os.getenv("POSTGRES_USER", "csai302"),
        password=os.getenv("POSTGRES_PASSWORD"), host=os.getenv("POSTGRES_HOST", "localhost"),
        port=int(os.getenv("POSTGRES_PORT", "5432")),
        database=os.getenv("POSTGRES_DB", "csai302")))


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--postgres", action="store_true")
    args = parser.parse_args()
    engine = course_engine() if args.postgres else create_engine("sqlite:///:memory:")
    seed(engine)
    with Session(engine) as session:
        viewer = QueryService(session, "viewer")
        print("ORM lookup:", [c.name for c in viewer.find_customer("Mona")])
        print("Injection input returns:", viewer.find_customer("' OR 1=1 --"))
        print("Bound report:", QueryService(session, "analyst").report(200))
        try:
            viewer.report(0)
        except PermissionError as error:
            print("Access denied:", error)
